# -*- coding: utf-8 -*-
"""Non-regression — le PERIMETRE DE MESURE est nomme, partage, et dit ce qu'il ne voit pas.

Chantier arrete par l'owner le 2026-09-08 : le chainon manquant de la boucle n'est pas
`autonomous_loop -> gain_gate`, c'est `autonomous_loop -> perimetre de mesure -> gain_gate`.
`juger_module_avec_gain` ne peut pas inventer ce qu'est une amelioration : sans tests
cibles, il rend GAIN_INDECIDABLE (cf. test_gain_indecidable_nr).

ANTI-DUP : ce perimetre n'est PAS neuf. Il existait, ENFERME en ligne dans
`forge_self_mutation.MutationCycle.run_cycle` (L305-310 avant extraction) — quatre
conventions de nommage filtrees sur l'existence reelle du fichier. Il etait donc
inutilisable par `forge_autonomous_loops`, qui emprunte pour cette raison le chemin
SANS gain (`juger_module`). On EXTRAIT, on ne reecrit pas : le comportement de
`forge_self_mutation` doit rester rigoureusement identique.

Les quatre conventions, pour `app/forge_x.py` :
    tests/test_forge_x.py · tests/nr/test_forge_x_nr.py
    tests/nr/test_x_nr.py · tests/test_x.py       (variante sans le prefixe forge_)

Hermetique : fichiers fabriques en tmp_path, racine injectee. Aucun test lance.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_mutation_judge import perimetre_mesure  # noqa: E402


def _fabriquer(base: Path, *rels: str) -> None:
    for r in rels:
        p = base / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def test_rien():\n    assert True\n", encoding="utf-8")


def test_trouve_la_convention_nr_prefixee(tmp_path):
    _fabriquer(tmp_path, "tests/nr/test_forge_x_nr.py")
    assert perimetre_mesure("app/forge_x.py", racine=tmp_path) == ["tests/nr/test_forge_x_nr.py"]


def test_trouve_la_convention_courte_sans_prefixe_forge(tmp_path):
    """C'est la variante qui rattrape le plus de modules du depot."""
    _fabriquer(tmp_path, "tests/nr/test_x_nr.py")
    assert perimetre_mesure("app/forge_x.py", racine=tmp_path) == ["tests/nr/test_x_nr.py"]


def test_ne_rend_que_des_fichiers_QUI_EXISTENT(tmp_path):
    """Un chemin conventionnel qui n'existe pas ferait echouer la mesure en silence."""
    assert perimetre_mesure("app/forge_absent.py", racine=tmp_path) == []


def test_cumule_les_conventions_sans_doublon(tmp_path):
    _fabriquer(tmp_path, "tests/test_forge_x.py", "tests/nr/test_forge_x_nr.py",
               "tests/nr/test_x_nr.py")
    r = perimetre_mesure("app/forge_x.py", racine=tmp_path)
    assert len(r) == len(set(r)), "aucun doublon : chaque test serait joue deux fois"
    assert set(r) == {"tests/test_forge_x.py", "tests/nr/test_forge_x_nr.py",
                      "tests/nr/test_x_nr.py"}


def test_accepte_les_deux_separateurs(tmp_path):
    """Le juge recoit des `rel` en \\ sous Windows et en / ailleurs."""
    _fabriquer(tmp_path, "tests/nr/test_forge_x_nr.py")
    a = perimetre_mesure("app/forge_x.py", racine=tmp_path)
    b = perimetre_mesure("app\\forge_x.py", racine=tmp_path)
    assert a == b == ["tests/nr/test_forge_x_nr.py"]


def test_un_module_hors_app_est_traite_pareil(tmp_path):
    _fabriquer(tmp_path, "tests/nr/test_forge_y_nr.py")
    assert perimetre_mesure("tools/forge_y.py", racine=tmp_path) == ["tests/nr/test_forge_y_nr.py"]


def test_le_comportement_de_self_mutation_est_INCHANGE(tmp_path):
    """L'extraction ne doit rien changer : memes 4 conventions, meme ordre de recherche.

    Reproduit l'expression exacte qui vivait en ligne dans run_cycle et compare.
    """
    import os

    _fabriquer(tmp_path, "tests/test_forge_x.py", "tests/nr/test_forge_x_nr.py",
               "tests/nr/test_x_nr.py", "tests/test_x.py")
    rel = "app/forge_x.py"
    _base = os.path.basename(rel)
    _stem = _base[:-3] if _base.endswith(".py") else _base
    _court = _stem[6:] if _stem.startswith("forge_") else _stem
    attendu = [c for c in ("tests/test_%s.py" % _stem, "tests/nr/test_%s_nr.py" % _stem,
                           "tests/nr/test_%s_nr.py" % _court, "tests/test_%s.py" % _court)
               if os.path.isfile(os.path.join(tmp_path, c))]
    assert perimetre_mesure(rel, racine=tmp_path) == attendu


def test_le_nom_public_ne_commence_pas_par_test():
    """Piege paye le 2026-09-08 : pytest collecte comme test toute fonction IMPORTEE
    dont le nom commence par `test`, puis reclame une fixture pour chacun de ses
    parametres (« fixture 'rel' not found »). Un helper public destine aux tests ne
    doit donc jamais porter ce prefixe — le contournement par alias ne protegerait
    que le fichier qui y pense."""
    import forge_mutation_judge as MJ

    assert not MJ.perimetre_mesure.__name__.startswith("test")
    assert not hasattr(MJ, "tests_cibles"), "l'ancien nom piegeur ne doit pas revenir"
