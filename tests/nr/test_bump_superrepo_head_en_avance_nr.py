# -*- coding: utf-8 -*-
"""NR -- 1/11 : CI de reference verte sur cdcda5267, poussee ; mais alpha local portait 8 commits de plus (hors CI).
`forge_bump_superrepo --commit` visait le HEAD local, non publie, et REFUSAIT : le bump du sha certifie devenait
impossible sans pousser du non-certifie. Quand le distant est un ANCETRE du HEAD (avance locale), on fige le sha
PUBLIE. La garde reste entiere : sha diverge (ni ancetre ni descendant du distant) -> refus."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_bump_superrepo as bs  # noqa: E402

# graphe : a <- b(tip) <- c(head local) ; x diverge
_ANCETRES = {("a", "b"), ("a", "c"), ("b", "c")}


def _anc(x, y):
    return (x, y) in _ANCETRES


def test_head_en_avance_fige_le_distant():
    sha, note = bs._sha_a_figer("c", "b", _anc)
    assert sha == "b" and "publie" in note


def test_head_en_retard_fige_le_head():
    assert bs._sha_a_figer("a", "b", _anc)[0] == "a"


def test_identiques_et_divergence():
    assert bs._sha_a_figer("b", "b", _anc) == ("b", "")
    sha, note = bs._sha_a_figer("x", "b", _anc)
    assert sha is None and "n'est PAS publie" in note


def test_main_passe_par_la_decision():
    src = (ROOT / "tools" / "forge_bump_superrepo.py").read_text(encoding="utf-8")
    assert "_sha_a_figer(sha, tip," in src
