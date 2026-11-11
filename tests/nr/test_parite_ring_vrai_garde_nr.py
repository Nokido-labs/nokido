"""NR : le profil de ring lit le VRAI bash_guard.py. Ses 5 tests sur fixtures restaient verts avec `target.name`, qui leve."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_parite_ring as P  # noqa: E402


def test_le_vrai_bash_guard_se_lit_sans_erreur_de_parse():
    r = P.analyser_bash_guard_ast(RACINE / "tools" / "bash_guard.py")
    assert "Erreur parse" not in r["details"]
    assert r["statut"] == P.STATUT_VRAI
    assert "bash_guard" not in sys.modules  # jamais importe : il lit stdin et sort a l'import
