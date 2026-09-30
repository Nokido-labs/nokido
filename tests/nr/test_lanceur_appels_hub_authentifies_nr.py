# -*- coding: utf-8 -*-
"""NR — le lanceur du bureau ne parle au hub ni sans jeton, ni sous un nom d'emprunt.

Mesure du 24/09 (vue d'audit du videur) : 12 appels « master_token + LAUNCHER » —
« LAUNCHER » n'est meme pas une identite du registre — et, a la lecture du code, l'appel
MUTANT `set_mode` partait SANS AUCUN jeton, avec un simple en-tete : une identite DECLAREE,
jamais prouvee (contrat AUTH-1/AUTH-4). Le lanceur est l'owner avec le jeton maitre : il
s'annonce donc MASTER (AUTH-2 : le maitre ne prend pas un nom d'organe).

Propriete verifiee sur l'AST (tient au refactoring) : tout dict d'en-tetes qui porte
`X-Agent-Name` porte aussi `Authorization`, et aucun ne s'annonce `LAUNCHER`.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "tools" / "nokido_launcher.py"


def _dicts_d_entetes():
    for n in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Dict):
            cles = {k.value: v for k, v in zip(n.keys, n.values)
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "X-Agent-Name" in cles:
                yield cles


def test_chaque_appel_porte_un_jeton():
    trouves = list(_dicts_d_entetes())
    assert trouves, "aucun appel au hub trouve : le test ne mesurerait rien"
    sans = [c for c in trouves if "Authorization" not in c]
    assert not sans, "%d appel(s) au hub sans jeton : identite declaree, jamais prouvee" % len(sans)


def test_aucun_nom_d_emprunt():
    noms = {c["X-Agent-Name"].value for c in _dicts_d_entetes()
            if isinstance(c["X-Agent-Name"], ast.Constant)}
    assert "LAUNCHER" not in noms, noms
