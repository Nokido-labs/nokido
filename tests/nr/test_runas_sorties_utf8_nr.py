# -*- coding: utf-8 -*-
"""NR -- un service lance sous runAs ecrit ses sorties en UTF-8 (15/10).

Mesure : le journal de NokidoTaskExecutorAntigravity portait « Aucune tǽche pending » -- l'enfant Python
ecrivait son pipe en cp1252 (aucun PYTHONIOENCODING), relu en UTF-8. Chemin REEL : la fonction qui prepare
l'environnement de l'enfant, sur les deux plateformes (`_preparer_environnement`).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_runas_launcher as rl  # noqa: E402


def test_l_enfant_ecrit_en_utf8():
    env = {"PATH": "x"}
    rl._preparer_environnement(env)
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_un_encodage_declare_par_le_service_est_garde():
    env = {"PATH": "x", "PYTHONIOENCODING": "utf-8:replace"}
    rl._preparer_environnement(env)
    assert env["PYTHONIOENCODING"] == "utf-8:replace"
