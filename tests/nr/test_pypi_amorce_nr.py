#!/usr/bin/env python3
"""NR — une amorce DANS une fonction n'est pas une amorce de module.

DEFAUT MESURE le 2026-09-10, deux fois, sur le meme malentendu.

D'abord dans le CORPS : `ci_local.py` porte `sys.path.insert(0, str(ROOT))` aux
lignes 1263 et 3133 — dans des fonctions. L'import migre, lui, vit dans
`_mesure_pip_audit_deportee()`, qui n'en a pas :

    from nokido_agent.tools.forge_deps_reconcilier import rapport_courant
    -> ModuleNotFoundError -> gate pip-audit NON MESURE

Le `sys.path` d'un processus n'est pas un contrat entre fonctions : une fonction
jamais appelee n'amorce rien.

Puis dans l'INSTRUMENT qui devait le detecter : `a_une_amorce_racine` faisait
`ast.walk` sur chaque noeud du body — donc il DESCENDAIT dans les fonctions et
comptait leurs insertions. Il annoncait 513 fichiers « deja amorces » ; apres
correction, 401. La meme confusion, dans le detecteur du defaut.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

am = pytest.importorskip("forge_pypi_amorce")


def _arbre(src: str) -> ast.Module:
    return ast.parse(src)


def test_une_insertion_au_niveau_module_compte():
    src = ("import sys\nfrom pathlib import Path\n"
           "ROOT = Path(__file__).resolve().parent.parent\n"
           "sys.path.insert(0, str(ROOT))\n")
    assert am.a_une_amorce_racine(_arbre(src)) is True


def test_une_insertion_DANS_UNE_FONCTION_ne_compte_PAS():
    """LE test. C'est exactement la forme de `ci_local.py`, et c'est ce qui a
    casse le gate pip-audit."""
    src = ("import sys\nfrom pathlib import Path\n"
           "ROOT = Path(__file__).resolve().parent.parent\n"
           "def plus_tard():\n"
           "    sys.path.insert(0, str(ROOT))\n"
           "    from nokido_agent.tools.x import y\n")
    assert am.a_une_amorce_racine(_arbre(src)) is False


def test_une_insertion_de_ZONE_ne_compte_pas_comme_amorce():
    """Inserer `app/` ne rend PAS le namespace atteignable : il vit a la racine.
    Compter les deux pareil ferait croire le corps amorce alors qu'il ne l'est
    pas."""
    src = ("import sys\nfrom pathlib import Path\n"
           "ROOT = Path(__file__).resolve().parent.parent\n"
           "sys.path.insert(0, str(ROOT / 'app'))\n")
    assert am.a_une_amorce_racine(_arbre(src)) is False


def test_une_insertion_dans_une_classe_ne_compte_pas():
    src = ("import sys\nclass A:\n    sys.path.insert(0, '/x')\n")
    assert am.a_une_amorce_racine(_arbre(src)) is False


def test_le_denominateur_des_candidats_est_non_vide():
    """Regle owner : un instrument au denominateur vide est NON-CERTIFIANT. Sans
    candidats, l'outil declarerait le corps sain sans avoir rien regarde."""
    c = am.candidats()
    assert len(c) > 100, f"seulement {len(c)} candidats : perimetre suspect"


def test_l_amorce_produite_est_parsable_et_idempotente():
    """Elle doit se poser sans casser le fichier, et ne jamais s'ajouter deux
    fois — deux amorces ne valent pas mieux qu'une."""
    ast.parse(am.AMORCE)
    src = "\"\"\"doc.\"\"\"\nimport os\n" + "\n" + am.AMORCE + "print(os.name)\n"
    ast.parse(src)
    assert am.a_une_amorce_racine(_arbre(src)) is True


# ── 2026-09-25 : l'instrument ignorait l'ORDRE ─────────────────────────────────────────────
# Mesure (epreuve « medecin ») : 43 points d'entree importent `nokido_agent` AVANT toute
# insertion de chemin, et l'outil en declarait 42 « deja amorces ». Deux d'entre eux,
# producteurs d'examens du corps, mouraient a l'import depuis 15 et 28 jours. Et
# `_point_d_insertion` posait l'amorce APRES les imports de tete -- donc apres l'import
# qu'elle doit preceder : c'est ce qui avait tue forge_memory_compactor le 2026-09-11.

FORME_DU_CODEMOD = ("import os\nimport sys\n\n"
                    "from nokido_agent.tools.forge_archeo_socle import noms_par\n\n"
                    "ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
                    "sys.path.insert(0, ROOT)\n")


def test_une_amorce_posee_APRES_l_import_du_namespace_ne_compte_pas():
    assert am.a_une_amorce_racine(_arbre(FORME_DU_CODEMOD)) is False


def test_une_boucle_sur_les_zones_n_est_pas_une_amorce_racine():
    """`for sub in ("app", "tools"): sys.path.insert(0, p)` -- l'argument est une VARIABLE,
    illisible par sa fin ; c'est la boucle qui dit qu'on n'insere que des zones."""
    src = ("import os\nimport sys\n"
           "ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
           "for sub in ('app', 'tools'):\n"
           "    p = os.path.join(ROOT, sub)\n"
           "    if p not in sys.path:\n"
           "        sys.path.insert(0, p)\n"
           "from nokido_agent.tools.x import y\n")
    assert am.a_une_amorce_racine(_arbre(src)) is False


def test_l_amorce_se_pose_AVANT_le_premier_import_du_namespace():
    arbre = _arbre(FORME_DU_CODEMOD)
    lignes = FORME_DU_CODEMOD.splitlines(keepends=True)
    pos = am._point_d_insertion(arbre, lignes)
    nouveau = "".join(lignes[:pos]) + "\n" + am.AMORCE + "".join(lignes[pos:])
    assert am.a_une_amorce_racine(ast.parse(nouveau)) is True, nouveau


# Points d'entree TRIES le 2026-09-25 : lances par chemin ET panne d'import PROUVEE (sys.path[0] =
# dossier du script, PYTHONPATH vide, miniforge3 et laforge_py314). Le tri des 66 a montre que
# l'ordre statique ne suffit pas a conclure : 4 des 6 lances s'importaient tres bien.
TRIES_ET_PROUVES = ("tools/forge_capability_execution_trace.py", "tools/forge_provider_reachability.py",
                    "tools/forge_embed_8099_mesure_bornee.py")


@pytest.mark.parametrize("rel", TRIES_ET_PROUVES)
def test_les_points_d_entree_tries_ont_une_amorce_racine_operante(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert am.a_une_amorce_racine(ast.parse(src)) is True, "%s : amorce absente, tardive ou limitee aux zones" % rel


def test_l_amorce_ne_precede_jamais_from_future():
    """`from __future__ import ...` doit rester la PREMIERE instruction : l'y
    faire preceder est une SyntaxError."""
    src = ('"""doc."""\nfrom __future__ import annotations\nimport sys\n'
           'if __name__ == "__main__":\n    print(1)\n')
    arbre = ast.parse(src)
    lignes = src.splitlines(keepends=True)
    pos = am._point_d_insertion(arbre, lignes)
    nouveau = "".join(lignes[:pos]) + "\n" + am.AMORCE + "".join(lignes[pos:])
    ast.parse(nouveau)   # ne doit pas lever
