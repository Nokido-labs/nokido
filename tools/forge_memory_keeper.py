#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_memory_keeper.py — OrganAgent KEEPER de la MÉMOIRE PARTAGÉE.

Décline le principe forge_roadmap_keeper (directive user : « fais ça pour memory aussi »)
sur la mémoire. OWNS la mémoire partagée (logs/lessons_learned.md + anchors RAG). Centralise
la CONSULTATION pour la FLUIDIFIER : présenter = lire la vue MATÉRIALISÉE / l'index interne
(rapide) ; l'indexation coûteuse reste à la TENUE (anchor/internalize), pas à la consultation.

FÉDÈRE (anti-dup, ne réimplémente RIEN) :
  - tenue / remember -> forge_self_correction.anchor_solution / session_summary (hippocampe).
  - INTERNALISE       -> forge_keeper_base.internalize (substrat souverain RAG, gouverné).
  - recent            -> forge_self_correction.read_lessons (lecture fichier = rapide).
  - recall(topic)     -> forge_keeper_base.find / consult (index FTS5 local, PAS Grep).

ANTI-DUP justifié : forge_self_correction = primitives mémoire ; forge_knowledge_concierge =
ROUTEUR de requêtes (portier). Ce keeper = l'OWNER+presenter dédié, point de consultation
CENTRAL et rapide de la mémoire partagée, conforme au contrat OrganAgent.

CLI : --present [recent|recall:<topic>|status|full] | --remember "<pb>::<sol>::<domaine>"
      | --status | --contract
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

LESSONS = ROOT / "logs" / "lessons_learned.md"


def remember(problem: str, solution: str, example: str = "", domain: str = "general") -> dict:
    """TENUE : ancre une leçon dans la mémoire (forge_self_correction) PUIS l'internalise
    sous le marqueur keeper (consultation centrale). Internalisation exige un repo writable."""
    out = {"anchored": None, "internalized": None}
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution
        out["anchored"] = anchor_solution(problem=problem, solution=solution,
                                           example=example, domain=domain)
    except Exception as e:  # noqa: BLE001
        out["anchored"] = {"ok": False, "error": str(e)}
    try:
        from nokido_agent.app.forge_keeper_base import internalize
        out["internalized"] = internalize("memory", f"{problem}\n{solution}", domain="reference")
    except Exception as e:  # noqa: BLE001
        out["internalized"] = {"ok": False, "error": str(e)}
    return out


def _recent(n: int = 2500) -> str:
    try:
        from nokido_agent.app.forge_self_correction import read_lessons
        return read_lessons(n) or "[mémoire vide]"
    except Exception as e:  # noqa: BLE001
        return f"[read_lessons KO: {e}]"


def lessons(topic: str, limit: int = 8) -> dict:
    """La MEME consultation que `recall`, en RECORDS et non en prose -- pour un RECEPTEUR.

    CE QUI A ETE PAYE (2026-09-07). La carte du corps (`forge_organ_agents`) declare la
    boucle de regeneration « memory_keeper(gaps/lessons) -> evolutionary_engine » en GAP P1
    depuis des semaines. Mesure : cet organe possede 1,1 Mo de lecons et un index FTS5, et
    n'exposait que de la PROSE (`recall`, `present` -> str). Un recepteur ne peut rien
    iterer dans un recit : l'afferent de la boucle etait emis pour un LECTEUR, pas pour un
    organe. Pendant ce temps `evolutionary_engine` tenait SES PROPRES lecons dans ses
    fiches de feedback -- deux memoires, aucune commissure.

    Trois etats, jamais deux : LU (items, meme vides) · ILLISIBLE (index indisponible ou
    en erreur). Un index injoignable n'est pas « aucune lecon ».
    """
    try:
        from nokido_agent.app.forge_keeper_base import find
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "motif": "find indisponible: %s" % type(e).__name__,
                "topic": topic, "items": []}
    try:
        hits = find(topic, limit=limit)
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "motif": "find a leve: %s" % type(e).__name__,
                "topic": topic, "items": []}
    items = [dict(h) for h in (hits or []) if isinstance(h, dict) and "source" in h]
    return {"etat": "LU", "motif": "", "topic": topic, "items": items}


def recall(topic: str, limit: int = 8) -> str:
    """Consultation rapide via l'index FTS5 local (souverain), pas un re-scan ni Grep."""
    try:
        from nokido_agent.app.forge_keeper_base import find
    except Exception as e:  # noqa: BLE001
        return f"[find indispo: {e}]"
    hits = find(topic, limit=limit)
    rows = [f"[{h['source']}] {h.get('preview', '')}" for h in hits if "source" in h]
    return "\n".join(rows) if rows else f"[aucun résultat pour '{topic}']"


def status() -> dict:
    sz = LESSONS.stat().st_size if LESSONS.exists() else 0
    return {"lessons_file": str(LESSONS), "exists": LESSONS.exists(), "bytes": sz,
            "owns": "logs/lessons_learned.md + RAG anchors"}


def present(view: str = "recent") -> str:
    if view.startswith("recall:"):
        return recall(view.split(":", 1)[1])
    if view == "status":
        return json.dumps(status(), ensure_ascii=False, indent=2)
    if view in ("full", "lessons"):
        return _recent(8000)
    return _recent()  # recent (défaut)


# Auto-enregistrement dans le registre central des keepers (découvrable portier/gate).
try:
    from nokido_agent.app.forge_keeper_base import register, keeper_contract
    CONTRACT = keeper_contract(
        "MEMORY_KEEPER", organ="memory/hippocampe",
        owns="logs/lessons_learned.md + RAG anchors (domain=reference)",
        triggers=["on_anchor", "session_end", "schedule_daily", "on_request"],
        connects_to=["forge_self_correction", "RAG", "forge_knowledge_concierge(portier)"],
        verbs=["remember", "present", "recall", "status"])
    register("memory", owns=CONTRACT["owns"], present=present, status=status,
             regen=None, contract=CONTRACT, source="module")
except Exception:  # noqa: BLE001 - base indispo -> keeper autonome quand même
    CONTRACT = {"agent": "MEMORY_KEEPER", "owns": "logs/lessons_learned.md", "kind": "KEEPER"}


def _main() -> int:
    ap = argparse.ArgumentParser(description="MEMORY keeper — tenue + présentation")
    ap.add_argument("--present", nargs="?", const="recent")
    ap.add_argument("--remember", help='format "<pb>::<sol>::<domaine>"')
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--contract", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.contract:
        print(json.dumps(CONTRACT, ensure_ascii=False, indent=2))
        return 0
    if a.status:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return 0
    if a.remember:
        parts = (a.remember.split("::") + ["", "", "general"])[:3]
        print(json.dumps(remember(parts[0], parts[1], domain=parts[2] or "general"),
                         ensure_ascii=False))
        return 0
    print(present(a.present or "recent"))
    return 0


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    chk(isinstance(present("recent"), str), "present(recent) -> str (lecture matérialisée)")
    chk(isinstance(recall("firewall OR ring"), str), "recall via index FTS5 -> str")
    st = status()
    chk("lessons_file" in st and "owns" in st, f"status: {st['exists']}")
    chk(CONTRACT.get("kind") == "KEEPER", "contrat OrganAgent KEEPER")
    chk("memory" in __import__("forge_keeper_base").KEEPER_REGISTRY, "auto-enregistré dans le registre")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_main())
