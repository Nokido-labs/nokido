"""NR -- un pytest imbrique (mesurer, scorecard) est enracine dans SON dossier : il ne parcourt jamais au-dessus.

Mesure 20/10 (CI de reference 46c8adfa5, 1 echec ; deja 477e02f93 et 63a63a812) : test_capsule_autopsie -> le pytest
imbrique de forge_mutation_judge.mesurer mourait en `FileNotFoundError ... tmp\\oracle_s4398_2v` sur un ERROR
`..\\..\\..\\..` : sa racine etait loin au-dessus du fichier, et la collecte de pytest >= 8 liste chaque dossier
ancetre -- des dossiers ou les temporaires d'AUTRES tests naissent et meurent en parallele. Course propre a la charge
de la reference (vert seul, vert dans l'arbre principal). Remede : --rootdir et --confcutdir = le dossier de la mesure.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_mutation_judge as J  # noqa: E402


class _R:
    returncode, stdout, stderr = 0, "1 passed in 0.1s", ""


def _valeur(cmd, option):
    for i, x in enumerate(cmd):
        if x == option and i + 1 < len(cmd):
            return cmd[i + 1]
        if isinstance(x, str) and x.startswith(option + "="):
            return x.split("=", 1)[1]
    return None


def test_mesurer_enracine_son_pytest_dans_son_dossier(tmp_path, monkeypatch):
    vus = []
    monkeypatch.setattr(J.subprocess, "run", lambda cmd, **k: vus.append(cmd) or _R())
    J.mesurer([str(tmp_path / "test_x.py")], cwd=str(tmp_path))
    assert vus and _valeur(vus[0], "--rootdir") == str(tmp_path), vus
    assert _valeur(vus[0], "--confcutdir") == str(tmp_path), vus
# Le meme contrat pour forge_scorecard vit dans test_scorecard_pytest_isole_nr.py : module de JUGE, la separation des
# pouvoirs interdit a l'agent juge de le modifier (RED en attente au socle, GREEN = derogation owner ou autre agent).
