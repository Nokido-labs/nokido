# -*- coding: utf-8 -*-
"""NR -- AGY recoit un modele LEGER par taille ; Argon jamais par defaut (owner 30/10).

Aide d'agy relue le 30/10 (sortie owner) : `--effort low|medium|high|xhigh|max`, `--model`, modeles
gemini-4-argon-{low,medium,high} (tres puissant, vide les tokens), gemini-3.8-flash-{low,medium,high}, claude-*-5-5-*,
gpt-oss-120b-medium. La table posait modele None (= le /model de l'owner, possiblement Argon) et des niveaux low|high.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_palier_effort as pe  # noqa: E402

pytestmark = pytest.mark.timeout(60)


@pytest.mark.parametrize("taille", ["S", "M", "L"])
def test_modele_leger_jamais_argon(taille):
    r = pe.resoudre("agy", taille)
    # owner 6/11 17:30 : Argon a tres peu de quota, « reste sur 3.8 et en dessous si necessaire »
    assert r["modele"] and r["modele"].startswith(("gemini-3.8-flash", "claude-sonnet", "claude-opus")), r
    # Paye le 6/11 : « --model gemini-3.8-flash-high conflicts with --effort=low », aucune session ne demarrait.
    assert r["modele"].rsplit("-", 1)[-1] == r["effort"], r
    assert "argon" not in r["modele"]


def test_niveaux_d_effort_relus_dans_l_aide():
    assert set(pe.DRAPEAUX_LUS["agy"]["niveaux_aide"]) >= {"low", "medium", "high"}


def test_l_executeur_passe_le_modele_a_agy():
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    corps = src.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]
    assert '"--model"' in corps
