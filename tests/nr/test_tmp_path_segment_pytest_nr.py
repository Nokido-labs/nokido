"""NR -- tout tmp_path porte un segment « pytest » a lui, quel que soit le basetemp.

Mesure 20/10 (pre-controle turbo job_a87b228e0b6f) : en --turbo, ci_local renomme le basetemp `bt` et xdist ajoute
`popen-gwN` ; le lot de la fixture tmp_path O(1) s'appelait `t<hash>`. Plus aucun segment `pytest*` ni TEMP :
forge_secrets._coffre_test refusait (a raison) le coffre de test et test_coffre_test_isole lisait la valeur
d'environnement. La regle de securite reste ; c'est le chemin des tests qui doit se dire « pytest ».
"""
from __future__ import annotations


def test_le_lot_du_tmp_path_se_dit_pytest(tmp_path):
    # 20/10 : plus de lot (MAX_PATH, cf. test_tmp_path_court_nr) -- c'est le dossier du test lui-meme qui se dit pytest
    assert tmp_path.name.lower().startswith("pytest"), tmp_path
