"""NR -- l'ecrivain de contournement du juge est GELE (debat swarm RSI du 2026-10-13, Q2).

`apply_mutation_with_git_guard` ecrivait du code sans passer par `mutable()` ni par le juge de gain, puis
commitait seul. Gele : il refuse et le DIT, AVANT la porte de l'evolution -- meme armee, rien n'est ecrit.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

GM = pytest.importorskip("nokido_agent.app.forge_guarded_mutation_loop")


def test_gele_par_defaut():
    assert GM.GELE is True


def test_refuse_sans_ecrire_meme_evolution_armee(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_EVOLUTION_ARMED", "1")
    journal = []
    monkeypatch.setattr(GM, "_log", lambda msg, level="INFO": journal.append((level, msg)))
    cible = tmp_path / "victime.py"
    assert GM.apply_mutation_with_git_guard(cible, "x = 1\n", "chore: x") is False
    assert not cible.exists(), "un ecrivain gele a ecrit"
    assert journal and "GELE" in journal[0][1], journal
