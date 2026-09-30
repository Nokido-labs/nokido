"""NR — flux isolation multi-agents : invariants PURS des 4 briques neuves.

Couvre forge_merge_gate, forge_anon_push, forge_pre_push_gate et
forge_mutation_controller (ajoutes le 2026-08-28) pour le cliquet de couverture NR.
On verifie l'EFFET (un garde sur un cas concret), pas le simple import ; aucun
subprocess ni reseau -- le merge gate est mocke.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _z in ("app", "tools"):
    _p = str(ROOT / _z)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_pre_push_gate_refuse_wip_et_laisse_suppression():
    from forge_pre_push_gate import verdict, ZERO
    ok, motif = verdict("refs/heads/wip/gemini", "a" * 40, "refs/heads/wip/gemini", ZERO)
    assert ok is False and "merge gate" in motif        # wip/* ne se pousse pas au remote
    ok2, _ = verdict("HEAD", ZERO, "refs/heads/feature", "c" * 40)
    assert ok2 is True                                  # suppression laissee passer
    ok3, _ = verdict("refs/heads/feature", "d" * 40, "refs/heads/feature", ZERO)
    assert ok3 is True                                  # branche non protegee, non-wip


def test_anon_push_trailer_cible_l_identite_agent():
    from forge_anon_push import _TRAILER
    assert _TRAILER.match("LaForge-Agent-Name: CLAUDE")
    assert _TRAILER.match("LaForge-Agent-Channel: UNKNOWN")
    assert _TRAILER.match("Co-Authored-By: X <y@z>")
    assert not _TRAILER.match("fix(core): un vrai sujet de commit")


def test_merge_gate_nomme_la_branche_et_respecte_l_override():
    from forge_merge_gate import _wip_branch, suite_nr
    assert _wip_branch("Gemini") == "wip/gemini"
    assert suite_nr(["tests/nr/x.py"]) == ["tests/nr/x.py"]   # override explicite respecte


def test_mutation_controller_ne_genere_pas_sans_amelioration(monkeypatch):
    import forge_mutation_controller as mc
    monkeypatch.setattr(
        "forge_merge_gate.merger",
        lambda agent, tests, apply: {"verdict": "NEUTRE", "applique": False,
                                     "decision": "REJET"},
    )
    r = mc.cycle("gemini", apply=False)
    assert r["verdict"] == "NEUTRE"
    assert "generation" not in r["etapes"]               # pas de generation si pas AMELIORE
