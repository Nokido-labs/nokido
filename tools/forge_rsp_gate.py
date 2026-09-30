"""forge_rsp_gate — RSP maison : matrice ASL (risque de la TACHE -> confinement requis).

Materialise la matrice ASL du doc docs/AI_SAFETY_APPLIQUEE_NOKIDO.md (Gap C) en gate
executable. COMPOSE forge_exec_tier (qui mappe trust de l'AGENT -> tier) en ajoutant la
dimension manquante : le RISQUE de la tache -> confinement minimal (sandbox + reseau +
ring + approbation owner). Formalise le "cadre unifie" que gVisor/Docker/rings
appliquaient ad-hoc.

Selftest : LAFORGE_PYTHON tools/forge_rsp_gate.py
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

__FORGE_COLOR__ = "immunitaire/guard : RSP maison, matrice ASL risque vers confinement"  # organe declare le 2026-09-06 (audit de raccordement)

# Rang de confinement des sandboxes du hub `run` (croissant = plus isole).
_SANDBOX_RANK = {
    "local": 0, "console": 0, "windows": 0,
    "ps_clm": 1, "wasm": 1,
    "gvisor": 2, "docker": 2,
}

# Mot-cle de tache -> niveau ASL. Defaut = ASL-2 (prudent) si inconnu.
_TASK_ASL = {
    "read": 1, "doc": 1, "summarize": 1, "search": 1, "rag_search": 1, "write_docs": 1, "classify": 1,
    "write_code": 2, "refactor": 2, "ast": 2, "analyze_code": 2, "code_review": 2, "write_tests": 2,
    "exec": 3, "run": 3, "run_tests": 3, "build": 3, "py_compile": 3, "benchmark_eval": 3,
    "recon": 4, "scan": 4, "exploit": 4, "pentest": 4, "security_audit": 4, "redteam": 4, "crawl": 4,
    "infra": 5, "hub_edit": 5, "service_restart": 5, "acl": 5, "secret_rotation": 5, "critical_code": 5,
}

# Confinement requis par niveau ASL. network: True (autorise) | False (interdit) |
# "isolated" (isole port-to-port, ouvert interdit). ring_max = ring maximal toleré.
ASL_REQ = {
    1: {"label": "lecture/redaction",    "min_rank": 0, "network": True,       "ring_max": 3, "owner": False},
    2: {"label": "modif code/AST",       "min_rank": 2, "network": False,      "ring_max": 2, "owner": False},
    3: {"label": "execution code/tests", "min_rank": 2, "network": False,      "ring_max": 2, "owner": False},
    4: {"label": "securite/recon/scan",  "min_rank": 2, "network": "isolated", "ring_max": 1, "owner": False},
    5: {"label": "infra/hub/ACL",        "min_rank": 0, "network": False,      "ring_max": 0, "owner": True},
}


def classify_asl(task_type: str) -> int:
    return _TASK_ASL.get((task_type or "").strip().lower(), 2)


def required_containment(task_type: str) -> dict:
    asl = classify_asl(task_type)
    return {"asl": asl, **ASL_REQ[asl]}


def _recommend(req: dict) -> str:
    if req["network"] == "isolated":
        return "docker"   # ephemere isole (style exegol)
    if req["min_rank"] >= 2:
        return "gvisor"
    return "local"


def gate(task_type: str, sandbox: str = "local", network: bool = False,
         ring: int = 3, owner_approved: bool = False, trust: str = "untrusted") -> dict:
    """Verifie que le confinement propose satisfait le RSP pour la tache.
    Retourne {ok, asl, label, reason, recommended_sandbox}."""
    req = required_containment(task_type)
    rank = _SANDBOX_RANK.get((sandbox or "").lower(), 0)
    reasons = []

    # Reconciliation RSP<->exec_tier (2026-06-25) : pour les ASL d'EXECUTION de code
    # (2/3), l'isolation est DEJA gouvernee par forge_exec_tier (TRUST->TIER :
    # trusted->tier0 local, untrusted->gVisor). Un acteur trusted en local est donc
    # conforme (on s'aligne sur pick_tier), sans quoi RSP ecraserait le modele
    # trust-tiered qui marche. ADDITIF : defaut trust=untrusted => plancher dur inchange.
    eff_min_rank = req["min_rank"]
    try:
        from nokido_agent.tools.forge_exec_tier import _TRUSTED as _EXEC_TRUSTED
        if req.get("asl") in (2, 3) and (trust or "").strip().lower() in _EXEC_TRUSTED:
            eff_min_rank = 0
    except Exception:  # noqa: BLE001
        pass

    if rank < eff_min_rank:
        reasons.append(f"sandbox '{sandbox}' (rang {rank}) < confinement requis {eff_min_rank} (gVisor/Docker)")

    net_req = req["network"]
    if net_req is False and network:
        reasons.append("reseau sortant interdit a ce niveau")
    elif net_req == "isolated" and network is True:
        reasons.append("reseau doit etre ISOLE (port-to-port), pas ouvert")

    if req["ring_max"] is not None and ring > req["ring_max"]:
        reasons.append(f"ring {ring} > max autorise {req['ring_max']}")

    if req["owner"] and not owner_approved:
        reasons.append("approbation OWNER requise (ASL-5 infra centrale)")

    return {
        "ok": not reasons,
        "asl": req["asl"],
        "label": req["label"],
        "reason": "; ".join(reasons) if reasons else "conforme RSP",
        "recommended_sandbox": _recommend(req),
    }


def selftest() -> bool:
    # (task, sandbox, network, ring, owner, attendu_ok)
    cases = [
        ("read",       "local",  True,  3, False, True),   # ASL-1 conforme
        ("write_code", "local",  False, 2, False, False),  # ASL-2 exige gVisor -> deny natif
        ("write_code", "gvisor", False, 2, False, True),   # conforme
        ("exec",       "gvisor", True,  2, False, False),  # ASL-3 reseau interdit -> deny
        ("recon",      "local",  False, 1, False, False),  # ASL-4 confinement insuffisant -> deny
        ("recon",      "docker", True,  1, False, False),  # ASL-4 reseau ouvert (doit etre isole) -> deny
        ("hub_edit",   "local",  False, 0, False, False),  # ASL-5 sans owner -> deny
        ("hub_edit",   "local",  False, 0, True,  True),   # ASL-5 owner-approuve -> ok
    ]
    all_ok = True
    for task, sb, net, ring, owner, expect in cases:
        r = gate(task, sb, net, ring, owner)
        verdict = "OK " if r["ok"] == expect else "FAIL"
        if r["ok"] != expect:
            all_ok = False
        print(f"  [{verdict}] ASL-{r['asl']} {task:11} sb={sb:7} net={net} ring={ring} owner={owner} "
              f"-> ok={r['ok']} ({r['reason'][:42]})")
    print("RSP GATE selftest:", "PASS" if all_ok else "FAIL")
    return all_ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
