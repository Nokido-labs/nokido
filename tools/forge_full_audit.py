"""forge_full_audit.py — AUDIT COMPLET consolide de Nokido (owner 2026-07-24).

N'invente aucun controle : il ORCHESTRE les audits qui existent deja et rend UN
rapport unique, trie par severite. Le but est qu'un audit ne depende plus de ce
qu'un agent pense a verifier ce jour-la.

Dimensions couvertes et QUI les couvre :
  1. code            -> tools/ci_local.py            (flake8/ruff/bandit/ast/licences/pytest/pip-audit)
  2. integration     -> tools/forge_organ_smoke_audit (les organes importent-ils et repondent-ils)
  3. configuration   -> tools/forge_config_refs_audit (references mortes : le trou PYBIN/codex/env)
  4. livraison       -> app/forge_delivery_integrity  (declare vs reel, CI, push, attestations)
  5. services        -> app/forge_sensor_fusion_probe (registre x port x heartbeat, desaccords)
  6. metriques       -> app/forge_metric_integrity    (Goodhart sur les scores internes)
  7. ressources      -> forge_resource_manager        (RAM/CPU/disque)

REGLE DE LECTURE : une dimension NON VERIFIABLE (droits, outil absent, hors reseau)
est rapportee comme telle et JAMAIS comptee comme saine — c'est le piege paye
plusieurs fois le 24-07 (« aucun submodule en derive » masquait un acces refuse,
un scanner CI muet se lisait vert, un scan de configs aveugle rendait 0).

CLI :
    LAFORGE_PYTHON tools/forge_full_audit.py            # rapport texte
    LAFORGE_PYTHON tools/forge_full_audit.py --json
    LAFORGE_PYTHON tools/forge_full_audit.py --fast     # saute ci_local (long)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PY = sys.executable


def _section(name: str, fn):
    t0 = time.perf_counter()
    try:
        ok, resume, details = fn()
        return {"dimension": name, "statut": ok, "resume": resume,
                "details": details, "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"dimension": name, "statut": "NON_VERIFIABLE",
                "resume": f"{type(e).__name__}: {str(e)[:160]}",
                "details": [], "ms": round((time.perf_counter() - t0) * 1000)}


def _run_script(rel: str, args: list[str] | None = None, timeout: int = 900):
    r = subprocess.run([PY, str(ROOT / rel), *(args or [])], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ── 1. code ────────────────────────────────────────────────────────────────
def _dim_code():
    rc, out = _run_script("tools/ci_local.py")
    bloquants = [l.strip() for l in out.splitlines() if l.strip().startswith("❌")]
    return ("OK" if rc == 0 else "ECHEC",
            "tous les gates bloquants passent" if rc == 0 else f"{len(bloquants)} gate(s) bloquant(s)",
            bloquants[:10])


# ── 2. integration ─────────────────────────────────────────────────────────
def _dim_integration():
    rc, out = _run_script("tools/forge_organ_smoke_audit.py", timeout=600)
    fails = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
    return ("OK" if rc == 0 else "ECHEC",
            "organes et phases du tick operationnels" if rc == 0 else f"{len(fails)} organe(s) KO",
            fails[:10])


# ── 3. configuration ───────────────────────────────────────────────────────
def _dim_config():
    from nokido_agent.tools import forge_config_refs_audit as cra

    morts = cra.scan()
    inobs = getattr(cra, "LAST_UNOBSERVABLE", 0)
    if morts:
        return ("ECHEC", f"{len(morts)} reference(s) morte(s)",
                [f"{m['fichier']}:{m['ligne']} -> {m['reference']}" for m in morts[:10]])
    if inobs:
        return ("NON_VERIFIABLE",
                f"0 morte MAIS {inobs} reference(s) hors perimetre de ce compte",
                ["relancer cote CLIENT pour conclure"])
    return ("OK", "aucune reference morte", [])


# ── 4. livraison ───────────────────────────────────────────────────────────
def _dim_livraison():
    from nokido_agent.app import forge_delivery_integrity as di

    r = di.scan()
    hi = [f for f in r["findings"] if f.get("severity") == "high"]
    return ("ECHEC" if hi else ("ATTENTION" if r["findings"] else "OK"),
            f"{r['count']} finding(s), dont {len(hi)} high",
            [f"{f['kind']}: {f['target']}" for f in r["findings"][:10]])


# ── 5. services ────────────────────────────────────────────────────────────
def _dim_services():
    from nokido_agent.app import forge_sensor_fusion_probe as sf

    res = sf.probe_all()
    if not res:
        return ("NON_VERIFIABLE", "registre superviseur muet", [])
    mal = [p for p in res if p["verdict"] != "sain"]
    desac = [p for p in res if p["desaccords"]]
    return ("ECHEC" if mal else ("ATTENTION" if desac else "OK"),
            f"{len(res)} services, {len(mal)} non sains, {len(desac)} en desaccord",
            [f"{p['service']}: {p['verdict']} | {'; '.join(p['desaccords'])[:110]}"
             for p in (mal + desac)[:10]])


# ── 6. metriques ───────────────────────────────────────────────────────────
def _dim_metriques():
    from nokido_agent.app import forge_metric_integrity as mi

    r = mi.scan()
    return ("ATTENTION" if r["count"] else "OK",
            f"{r['count']} derive(s) de scoring",
            [f"{f['kind']}: {f['target']}" for f in r["findings"][:10]])


# ── 7. ressources ──────────────────────────────────────────────────────────
def _dim_ressources():
    import shutil

    from nokido_agent.app import forge_resource_manager as rm

    s = rm.get_snapshot()
    det, statut = [], "OK"
    ram = float(s.get("ram_pct") or 0)
    if ram >= 85:
        statut, _ = "ATTENTION", det.append(f"RAM {ram}% (>=85 : le gate refuse les spawns)")
    for drv in ("C:\\", "D:\\", "%NOKIDO_DATA%\\"):
        if os.path.exists(drv):
            t, u, f = shutil.disk_usage(drv)
            pct = u / t * 100
            if pct >= 90:
                statut = "ATTENTION"
                det.append(f"{drv} {pct:.0f}% utilise ({f / 2**30:.0f} Go libres)")
    return (statut, f"RAM {ram}%, disques verifies", det)


DIMENSIONS = [
    ("code", _dim_code),
    ("integration", _dim_integration),
    ("configuration", _dim_config),
    ("livraison", _dim_livraison),
    ("services", _dim_services),
    ("metriques", _dim_metriques),
    ("ressources", _dim_ressources),
]

_ORDRE = {"ECHEC": 0, "NON_VERIFIABLE": 1, "ATTENTION": 2, "OK": 3}


def audit(fast: bool = False) -> dict:
    dims = [(n, f) for n, f in DIMENSIONS if not (fast and n == "code")]
    res = [_section(n, f) for n, f in dims]
    res.sort(key=lambda r: _ORDRE.get(r["statut"], 9))
    compte = {}
    for r in res:
        compte[r["statut"]] = compte.get(r["statut"], 0) + 1
    return {"ts": time.time(), "dimensions": res, "synthese": compte,
            "verdict": "ECHEC" if compte.get("ECHEC") else
                       ("NON_VERIFIABLE" if compte.get("NON_VERIFIABLE") else
                        ("ATTENTION" if compte.get("ATTENTION") else "OK"))}


def _main() -> int:
    ap = argparse.ArgumentParser(description="Audit complet consolide")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fast", action="store_true", help="saute les gates code (longs)")
    a = ap.parse_args()
    r = audit(fast=a.fast)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print("=" * 70)
        print(f"AUDIT COMPLET NOKIDO — verdict global : {r['verdict']}")
        print("=" * 70)
        for d in r["dimensions"]:
            print(f"\n[{d['statut']:15}] {d['dimension']:14} {d['resume']}  ({d['ms']} ms)")
            for x in d["details"]:
                print(f"      - {x}")
        print("\n" + "-" * 70)
        print("synthese :", json.dumps(r["synthese"], ensure_ascii=False))
        print("NB : NON_VERIFIABLE n'est PAS sain — c'est une zone non observee.")
    return 1 if r["verdict"] in ("ECHEC",) else 0


if __name__ == "__main__":
    sys.exit(_main())
