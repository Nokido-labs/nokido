# -*- coding: utf-8 -*-
"""NR — les instruments du chantier PyPI ne convertissent JAMAIS un manque en succes.

__FORGE_COLOR__ = "qualite/build : non-regression des verdicts du chantier PyPI"

Trois outils de mesure, un seul contrat : `SUCCESS` / `CERTIFIE` se MERITE, et
tout ce qui n'a pas ete mesure produit un etat NON-CERTIFIANT — jamais un vert
par defaut. C'est la regle owner du chantier :

    « Ne jamais convertir STOP_NON_CERTIFIANT en FAIL pour forcer une
      progression. Ne jamais le convertir en SUCCESS pour permettre une
      publication. »

Ces fonctions sont PURES (dict -> verdict), donc testables sans venv, sans
reseau et sans effet de bord. Elles sont le dernier filtre avant une decision
de publication : si l'une d'elles ment, le mandat entier ment.

Ecrit le 2026-09-10 apres que la CI de reference a signale trois modules ajoutes
sans aucun NR (`test_nr_coverage_ratchet_nr`). Le cliquet a eu raison : ces
instruments decident d'une PUBLICATION et n'avaient rien qui les garde.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

FV = pytest.importorskip("forge_pypi_freshvenv")
PR = pytest.importorskip("forge_pypi_prototype")
LA = pytest.importorskip("forge_pypi_prototype_layout")

_SONDE_COMPLETE = {
    "import_namespace": True,
    "import_app": True,
    "import_tools": True,
    "capacite_ok": True,
    "checkout_independant": True,
}
_ENTRY_OK = {"nokido": {"rc": 0}, "nokido-hub": {"rc": 0}}


# ------------------------------------------------- fresh venv (3 niveaux)


def test_freshvenv_le_chemin_complet_donne_SUCCESS():
    """Denominateur du fichier : sans ce cas, tous les tests de refus
    passeraient meme si la fonction refusait TOUJOURS."""
    _v, global_, _m = FV.verdict(dict(_SONDE_COMPLETE), 0, dict(_ENTRY_OK))
    assert global_ == "SUCCESS", f"le chemin complet doit certifier, obtenu {global_}"


def test_freshvenv_independance_NON_MESUREE_est_NON_CERTIFIANT_pas_SUCCESS():
    """Le piege central du chantier : tout le reste peut etre vert, une
    installation dont l'independance au checkout n'a pas ete mesuree ne prouve
    RIEN — elle a pu reussir en lisant le depot."""
    sonde = dict(_SONDE_COMPLETE)
    sonde.pop("checkout_independant")
    _v, global_, motif = FV.verdict(sonde, 0, dict(_ENTRY_OK))
    assert global_ == "STOP_NON_CERTIFIANT", f"obtenu {global_} ({motif})"


def test_freshvenv_checkout_ATTEIGNABLE_invalide_tout():
    """Mesure FAUSSE, pas mesure absente : c'est un FAIL, pas un STOP."""
    sonde = dict(_SONDE_COMPLETE, checkout_independant=False,
                 chemins_du_depot=["C:/depot/app"])
    _v, global_, motif = FV.verdict(sonde, 0, dict(_ENTRY_OK))
    assert global_ == "FAIL", f"obtenu {global_}"
    assert "sys.path" in motif, "le motif doit nommer ce qui a ete vu"


def test_freshvenv_installation_NON_TENTEE_ne_certifie_pas():
    """`install_rc is None` = on n'a pas installe. Un niveau non renseigne reste
    None et `trancher` doit refuser de conclure."""
    _v, global_, _m = FV.verdict(dict(_SONDE_COMPLETE), None, dict(_ENTRY_OK))
    assert global_ != "SUCCESS", "une installation non tentee ne peut pas certifier"


def test_freshvenv_un_entry_point_MUET_ne_vaut_pas_un_entry_point_OK():
    """`rc=None` sur un point d'entree : il n'a pas repondu. Le compter comme
    reussi serait la faute exacte que ce chantier combat."""
    _v, global_, _m = FV.verdict(dict(_SONDE_COMPLETE), 0, {"nokido": {"rc": None}})
    assert global_ != "SUCCESS", "un entry point muet ne prouve pas qu'il fonctionne"


# ------------------------------------------------- prototype namespace


def test_prototype_un_champ_NON_MESURE_donne_NON_CERTIFIANT():
    etat, motif = PR.verdict_prototype(
        {"import_namespace": True, "import_frere": True}, 0)
    assert etat == "NON_CERTIFIANT", f"obtenu {etat}"
    assert "sys_path_pollue" in motif, "le champ manquant doit etre NOMME"


def test_prototype_entry_point_NON_MESURE_donne_NON_CERTIFIANT():
    sonde = {"import_namespace": True, "import_frere": True, "sys_path_pollue": False}
    etat, motif = PR.verdict_prototype(sonde, None)
    assert etat == "NON_CERTIFIANT" and "entry_point" in motif


def test_prototype_un_sys_path_POLLUE_est_un_FAIL():
    sonde = {"import_namespace": True, "import_frere": True, "sys_path_pollue": True}
    etat, _m = PR.verdict_prototype(sonde, 0)
    assert etat == "FAIL", f"un checkout dans sys.path invalide la preuve, obtenu {etat}"


def test_prototype_le_chemin_complet_CERTIFIE():
    sonde = {"import_namespace": True, "import_frere": True, "sys_path_pollue": False}
    etat, _m = PR.verdict_prototype(sonde, 0)
    assert etat == "CERTIFIE"


# ------------------------------------------------- layout package-dir


_INSTALLE_OK = {"import_namespace": True, "import_app": True,
                "import_tools_vers_app": True, "sys_path_pollue": False}
_CHECKOUT_OK = {"checkout_import_app": True, "checkout_import_tools": True}


def test_layout_le_MODE_CHECKOUT_non_mesure_donne_NON_CERTIFIANT():
    """`package-dir` doit tenir dans les DEUX modes. Ne mesurer que le mode
    installe laisserait passer une mise en page qui casse le depot."""
    etat, motif = LA.verdict_layout(dict(_INSTALLE_OK), {}, 0)
    assert etat == "NON_CERTIFIANT", f"obtenu {etat}"
    assert "checkout_import_app" in motif


def test_layout_un_seul_mode_casse_suffit_a_FAIL():
    etat, _m = LA.verdict_layout(dict(_INSTALLE_OK),
                                 dict(_CHECKOUT_OK, checkout_import_tools=False), 0)
    assert etat == "FAIL"


def test_layout_le_chemin_complet_CERTIFIE():
    etat, _m = LA.verdict_layout(dict(_INSTALLE_OK), dict(_CHECKOUT_OK), 0)
    assert etat == "CERTIFIE"


# ------------------------------------------------- interdits du mandat


@pytest.mark.parametrize("module", [FV, PR, LA])
def test_aucun_outil_n_emploie_une_option_d_installation_INTERDITE(module):
    """`--no-index` et `--find-links` vers le depot nourriraient l'installation
    de ce qu'on veut precisement exclure : elle reussirait sans rien prouver.

    On lit le CODE prive de ses commentaires — ces trois modules EXPLIQUENT
    justement pourquoi ils ne les emploient pas, et un garde qui compte les mots
    de sa propre explication crie a faux (paye six fois sur ce depot).
    """
    import io
    import tokenize

    src = Path(module.__file__).read_text(encoding="utf-8")
    jetons = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            jetons.append(tok.string)
    code = " ".join(jetons)
    for interdit in ("--no-index", "--find-links"):
        assert interdit not in code, (
            f"{Path(module.__file__).name} emploie {interdit} : l'installation "
            "serait nourrie hors index et la preuve ne vaudrait rien")


@pytest.mark.parametrize("module", [FV, PR, LA])
def test_chaque_outil_RETIRE_PYTHONPATH_du_sous_processus(module):
    """Un `PYTHONPATH` herite rend le checkout importable : le venv « neuf »
    verrait le depot, et la preuve d'independance serait fabriquee."""
    src = Path(module.__file__).read_text(encoding="utf-8")
    assert 'env.pop("PYTHONPATH"' in src, (
        f"{Path(module.__file__).name} n'assainit pas PYTHONPATH")
