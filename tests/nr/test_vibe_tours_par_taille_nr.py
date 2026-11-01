# -*- coding: utf-8 -*-
"""NR -- 30/10 (reglages des CLI) : Vibe avait un plafond de tours FIXE (60) quelle que soit la taille de la tache,
quand Claude headless suit la taille (15/40/80). Vibe suit desormais la taille (S 15, M 40, L 60) ; taille inconnue
= 60 comme avant ; la variable LAFORGE_VIBE_MAX_TURNS l'emporte toujours."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as fte  # noqa: E402


def _tours(args):
    return args[args.index("--max-turns") + 1]


def test_tours_suivent_la_taille(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_VIBE_MAX_TURNS", raising=False)
    assert _tours(fte._args_vibe(tmp_path, taille="S")) == "15"
    assert _tours(fte._args_vibe(tmp_path, taille="M")) == "40"
    assert _tours(fte._args_vibe(tmp_path, taille="L")) == "60"


def test_taille_inconnue_garde_60(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_VIBE_MAX_TURNS", raising=False)
    assert _tours(fte._args_vibe(tmp_path)) == "60"


def test_variable_d_environnement_l_emporte(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_VIBE_MAX_TURNS", "7")
    assert _tours(fte._args_vibe(tmp_path, taille="L")) == "7"
