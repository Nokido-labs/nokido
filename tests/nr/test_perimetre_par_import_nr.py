# -*- coding: utf-8 -*-
"""Non-regression — le perimetre de mesure voit AUSSI les tests qui IMPORTENT le module.

Correction owner du 2026-09-08 : « attention, il y a beaucoup de modules, certains
vivent dans tools, d'autres ne sont pas detectes par ton analyse ».

MESURE qui a suivi, sur un denominateur enfin complet (2413 modules .py de app/ et
tools/, recursif, hors _attic/legacy/__pycache__ — la mesure precedente n'en voyait
que 1335, les forge_*.py de la RACINE) :

    couvert par convention        183   7,6 %
    couvert par IMPORT seulement  264  10,9 %   <- invisible au capteur d'origine
    aucun test trouve            1966  81,5 %

Autrement dit le capteur par conventions RATAIT 264 modules, soit 59 % de plus que
ce qu'il voyait, et son « 86,7 % sans couverture » melangeait « aucun test » avec
« test present, hors convention ». Exemple mesure : `forge_agent_proxy` est exerce
par deux NR, dont aucun ne porte son nom.

C'est le motif deja paye ailleurs dans le corps : un capteur qui rend la meme valeur
pour « il n'y a rien » et pour « je n'ai pas su voir ». Un test qui importe un module
l'EXERCE : c'est le signal le plus honnete disponible, et il est gratuit.

BORNE : jouer tous les importateurs peut couter cher (`mesurer` lance un pytest par
fichier). Le perimetre est donc borne, et il DIT ce qu'il ecarte — une borne muette
serait le motif `borne_trop_serree`, deja paye sur 377 documents de veille.

Hermetique : arborescence fabriquee en tmp_path, racine injectee, aucun test lance.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_mutation_judge import perimetre_mesure, perimetre_mesure_detail  # noqa: E402


def _ecrire(base: Path, rel: str, contenu: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")


def test_un_test_qui_importe_le_module_est_retenu(tmp_path):
    """Aucune convention de nommage ne relie ces deux fichiers, l'import si."""
    _ecrire(tmp_path, "app/forge_zzz.py", "def f():\n    return 1\n")
    _ecrire(tmp_path, "tests/nr/test_tout_autre_chose_nr.py",
            "from forge_zzz import f\n\n\ndef test_f():\n    assert f() == 1\n")
    assert perimetre_mesure("app/forge_zzz.py", racine=tmp_path) == \
        ["tests/nr/test_tout_autre_chose_nr.py"]


def test_import_module_entier_aussi(tmp_path):
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/test_divers.py", "import forge_zzz\n\n\ndef test_x():\n    assert 1\n")
    assert perimetre_mesure("app/forge_zzz.py", racine=tmp_path) == ["tests/test_divers.py"]


def test_une_simple_MENTION_ne_suffit_pas(tmp_path):
    """Citer le nom dans un commentaire ou une chaine n'exerce rien."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/test_mention.py",
            "# on parle de forge_zzz ici\nNOM = 'forge_zzz'\n\n\ndef test_r():\n    assert 1\n")
    assert perimetre_mesure("app/forge_zzz.py", racine=tmp_path) == []


def test_la_convention_reste_prioritaire(tmp_path):
    """Le test qui porte le nom du module passe devant les importateurs."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_forge_zzz_nr.py", "import forge_zzz\n\n\ndef test_a():\n    assert 1\n")
    _ecrire(tmp_path, "tests/test_aaa_autre.py", "import forge_zzz\n\n\ndef test_b():\n    assert 1\n")
    r = perimetre_mesure("app/forge_zzz.py", racine=tmp_path)
    assert r[0] == "tests/nr/test_forge_zzz_nr.py", r


def test_aucun_doublon_quand_la_convention_importe_aussi(tmp_path):
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_forge_zzz_nr.py", "import forge_zzz\n\n\ndef test_a():\n    assert 1\n")
    r = perimetre_mesure("app/forge_zzz.py", racine=tmp_path)
    assert r == ["tests/nr/test_forge_zzz_nr.py"]


def test_la_borne_DIT_ce_qu_elle_ecarte(tmp_path):
    """Une borne muette ferait croire a une couverture plus etroite qu'elle n'est."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    for i in range(12):
        _ecrire(tmp_path, "tests/test_i%02d.py" % i,
                "import forge_zzz\n\n\ndef test_n():\n    assert 1\n")
    d = perimetre_mesure_detail("app/forge_zzz.py", racine=tmp_path, max_tests=8)
    assert len(d["retenus"]) == 8
    assert len(d["ecartes"]) == 4
    assert d["borne"] == 8
    assert all(e.startswith("tests/") for e in d["ecartes"]), "les ecartes sont NOMMES"


def test_le_detail_separe_convention_et_import(tmp_path):
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    _ecrire(tmp_path, "tests/nr/test_forge_zzz_nr.py", "def test_a():\n    assert 1\n")
    _ecrire(tmp_path, "tests/test_via_import.py", "import forge_zzz\n\n\ndef test_b():\n    assert 1\n")
    d = perimetre_mesure_detail("app/forge_zzz.py", racine=tmp_path)
    assert d["par_convention"] == ["tests/nr/test_forge_zzz_nr.py"]
    assert d["par_import"] == ["tests/test_via_import.py"]


def test_module_sans_aucun_test_rend_une_liste_vide(tmp_path):
    _ecrire(tmp_path, "app/forge_orphelin.py", "x = 1\n")
    d = perimetre_mesure_detail("app/forge_orphelin.py", racine=tmp_path)
    assert d["retenus"] == [] and d["ecartes"] == []


def test_l_ordre_est_deterministe(tmp_path):
    """Deux appels doivent rendre la meme liste : sinon la baseline n'est pas comparable."""
    _ecrire(tmp_path, "app/forge_zzz.py", "x = 1\n")
    for n in ("b", "a", "c"):
        _ecrire(tmp_path, "tests/test_%s.py" % n, "import forge_zzz\n\n\ndef test_n():\n    assert 1\n")
    assert perimetre_mesure("app/forge_zzz.py", racine=tmp_path) == \
        perimetre_mesure("app/forge_zzz.py", racine=tmp_path)
