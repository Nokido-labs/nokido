# -*- coding: utf-8 -*-
"""NR -- le prompt d'AGY commence par le PREFIXE STABLE (regles fixes de l'executeur), la consigne variable en fin.

Chasse aux tokens (owner 30/10) : le prompt etait `desc + _consigne_agy(...)` -- la partie VARIABLE en tete, si bien
qu'aucun cache de prefixe (KV / prompt cache du fournisseur, cf. litellm `cache_control`) ne pouvait servir d'une
tache a l'autre. Contrat : `_consigne_agy(workdir)` (regles fixes puis chemin) AVANT la consigne de la tache.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as te  # noqa: E402

SRC = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
CORPS = SRC.split("def _delegate_to_agy", 1)[1].split("\ndef ", 1)[0]

pytestmark = pytest.mark.timeout(60)


def test_le_prompt_commence_par_les_regles_fixes():
    ligne = next(l for l in CORPS.splitlines() if "cmd = [" in l and "--print" in l)
    assert ligne.index("_consigne_agy(workdir)") < ligne.index("desc"), ligne


def test_la_consigne_commence_par_la_partie_fixe():
    a, b = te._consigne_agy(r"C:\w\a"), te._consigne_agy(r"C:\w\b")
    commun = 0
    while commun < min(len(a), len(b)) and a[commun] == b[commun]:
        commun += 1
    assert commun > 200, "le prefixe commun a deux taches doit porter les regles fixes"
