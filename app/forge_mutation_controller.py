#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""app/forge_mutation_controller.py -- le KERNEL DE MUTATION (brief §6, §9, §11).

UNIFIE les briques existantes en UN flux "agent = producteur de patch" :
    worktree(agent) -> agent edite+commit dans wip/<agent> -> MERGE GATE (juge sur
    invariants tests/nr) -> si AMELIORE : merge + GENERATION restaurable.

ANTI-DUP total : n'implemente RIEN, orchestre forge_worktree (isolation),
forge_merge_gate (juge wip->alpha), forge_generation (etat immuable restaurable).
Le brief §11 listait forge_mutation_controller / forge_baseline / forge_provenance /
forge_recovery ; les trois derniers EXISTENT deja sous d'autres noms -- baseline =
forge_mutation_judge.mesurer, provenance = forge_session_provenance, recovery =
forge_capability_recovery. Ce module est le CONTROLEUR qui les enchaine, pas un doublon.

Owner-run. dry-run par defaut (le merge reel exige --apply, propage au merge gate).
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/orchestr : kernel de mutation, unifie les briques d'automutation"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


def cycle(agent: str, tests=None, apply: bool = False) -> dict:
    """Flux complet pour <agent>. Suppose que l'agent a DEJA commite son travail dans
    sa branche wip/<agent> (via son worktree isole). Enchaine isolation -> arbitrage
    -> generation, sans creer/juger/merger RIEN de plus que les briques dediees."""
    from nokido_agent.tools.forge_merge_gate import merger

    r = {"agent": agent, "etapes": {}}
    # ARBITRAGE : merge gate -- mesure alpha vs worktree sur les invariants, merge
    # wip->alpha SEULEMENT si AMELIORE. L'ISOLATION (create du worktree) est en AMONT
    # (declencheur au lancement de l'agent, forge_cli_route) ; merger() gere proprement
    # son absence (PAS_DE_WORKTREE) -- le controleur ne cree donc rien.
    ev = merger(agent, tests, apply)
    r["etapes"]["merge_gate"] = ev
    r["verdict"] = ev.get("verdict")
    r["decision"] = ev.get("decision")
    # 3. GENERATION : si le merge a eu lieu, inscrire un etat immuable restaurable
    if ev.get("applique"):
        try:
            from nokido_agent.app.forge_generation import capturer_si_absent
            gen = capturer_si_absent(tests={"invariants_nr": "PASS"}, agent=agent,
                                     note="merge %s (AMELIORE via merge gate)" % agent)
            r["etapes"]["generation"] = gen
        except Exception as exc:  # noqa: BLE001 - la generation ne doit pas casser le merge deja fait
            r["etapes"]["generation_err"] = "%s: %s" % (type(exc).__name__, exc)
    return r


def main():
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Kernel de mutation : worktree -> juge -> merge -> generation")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--apply", action="store_true", help="merge reel si AMELIORE (defaut: dry-run)")
    ap.add_argument("--tests", nargs="*", default=None, help="suite d'invariants (defaut: tests/nr)")
    a = ap.parse_args()
    print(json.dumps(cycle(a.agent, a.tests, a.apply), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
