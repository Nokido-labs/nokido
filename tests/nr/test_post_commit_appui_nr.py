# -*- coding: utf-8 -*-
"""Non-regression — un module NEUF est instrumente a l'evenement, pas au prochain sommeil.

Correction de direction, owner 2026-09-08 : « l'approche par analogie du corps devrait
t'indiquer sur quels organes le brancher pour qu'il soit plus reactif sans provoquer
d'embolie ».

Le premier cablage visait NREM1 (sommeil leger). Mesure : NREM1 tire toutes les ~41 h,
et le lot est borne a 40 modules — soit 46 nuits pour rattraper 1824 modules. Surtout,
l'analogie etait FAUSSE : instrumenter un module neuf n'est pas une CONSOLIDATION,
c'est une reponse a un EVENEMENT. Le bon organe est donc le post-commit, pas la phase
de sommeil.

POURQUOI L'EMBOLIE EST IMPOSSIBLE ICI, et ce n'est pas une precaution ajoutee :
  - le volume est borne PAR NATURE — un commit apporte quelques modules, pas mille ;
  - `forge_post_commit` porte DEJA le garde `should_use_hub` / `MAX_FILES_HUB`, ecrit
    apres qu'un commit de 451 fichiers ait declenche ~2255 POST vers le hub. On
    reutilise ce garde paye au lieu d'en inventer un.

Repartition finale des rythmes, par organe :
    post-commit  -> a l'evenement : le module neuf, tout de suite (REACTIF)
    NREM1        -> rattrapage de fond, 40 par nuit (ENTRETIEN)

Hermetique : fonction pure, chemins fabriques, aucun git, aucune ecriture.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_post_commit import MAX_FILES_HUB, modules_a_instrumenter  # noqa: E402


def test_retient_un_module_python_de_app_ou_tools():
    r = modules_a_instrumenter([Path("app/forge_neuf.py"), Path("tools/forge_autre.py")],
                               perimetre=lambda rel: [])
    assert r == ["app/forge_neuf.py", "tools/forge_autre.py"]


def test_ignore_ce_qui_n_est_pas_du_python():
    r = modules_a_instrumenter([Path("docs/GUIDE.md"), Path("config/x.json")],
                               perimetre=lambda rel: [])
    assert r == []


def test_ignore_les_tests_eux_memes():
    """Instrumenter un test avec un test d'appui n'aurait aucun sens."""
    r = modules_a_instrumenter([Path("tests/nr/test_quelque_chose_nr.py")],
                               perimetre=lambda rel: [])
    assert r == []


def test_ignore_un_module_qui_a_DEJA_un_perimetre():
    r = modules_a_instrumenter([Path("app/forge_couvert.py")],
                               perimetre=lambda rel: ["tests/nr/test_forge_couvert_nr.py"])
    assert r == []


def test_ignore_les_fichiers_ecartes_du_denominateur():
    """Meme critere que la mesure : un jetable n'entre pas dans la couverture."""
    r = modules_a_instrumenter([Path("tools/tmp_essai.py"), Path("app/__init__.py")],
                               perimetre=lambda rel: [])
    assert r == []


def test_un_commit_VOLUMINEUX_ne_declenche_rien():
    """Anti-embolie : au-dela du plafond deja paye, on s'abstient et on le dit.

    Le garde n'est pas neuf — `MAX_FILES_HUB` a ete pose apres un commit de 451
    fichiers qui avait fait ~2255 POST vers le hub.
    """
    gros = [Path("app/forge_%d.py" % i) for i in range(MAX_FILES_HUB + 5)]
    r = modules_a_instrumenter(gros, perimetre=lambda rel: [])
    assert r == []


def test_juste_sous_le_plafond_ca_passe():
    lot = [Path("app/forge_%d.py" % i) for i in range(MAX_FILES_HUB)]
    r = modules_a_instrumenter(lot, perimetre=lambda rel: [])
    assert len(r) == MAX_FILES_HUB


def test_les_chemins_sont_normalises_en_slash():
    r = modules_a_instrumenter([Path("app") / "forge_x.py"], perimetre=lambda rel: [])
    assert r == ["app/forge_x.py"], "le juge attend des chemins en slash"
