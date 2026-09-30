# -*- coding: utf-8 -*-
"""Non-regression — DEUX metriques de couverture, jamais fusionnees.

Arbitrage owner du 2026-09-08, apres la mesure qui a corrige mon propre capteur :

  1. `perimetre non vide` — le gain gate PEUT se prononcer sur ce module.
     Objectif 100 %, atteignable par generation de tests d'appui.
  2. `couverture prouvee`  — un test EXERCE reellement le comportement.
     JAMAIS optimisee automatiquement, reservee a l'audit.

Pourquoi la separation est un invariant et pas une preference : un systeme qui publie
ses scores et optimise dessus tombe sous Goodhart PAR CONSTRUCTION (entree P1 du
dossier de veille). Generer un test d'import par module ferait passer la couverture de
18,5 % a ~100 % en une nuit SANS que rien ne soit mieux teste. Fusionner les deux
chiffres fabriquerait donc exactement le faux calme que la constitution interdit.

CRITERE D'ECARTEMENT — inspectable, et volontairement ETROIT. Mesure du 2026-09-08 :
un premier critere « jetables » embarquait 80 modules LEGITIMES (`app/collab_modes/_core.py`,
`_arbitration.py`, `app/_internal/*`) parce qu'il ecartait tout basename prefixe `_`.
Ne sont ecartes que trois groupes verifies fichier par fichier :
  - `tmp_*`         117 fichiers de travail jetables (tmp_arxiv_test, tmp_ask_capture...)
  - `app/backups/`    8 snapshots dates (auto_boot_2026...)
  - `__init__.py`    17 fichiers de paquet, pas des unites de comportement
Un module a prefixe `_` RESTE dans le denominateur : c'est un module interne, pas un dechet.

Hermetique : arborescence fabriquee en tmp_path. Aucun scan du depot reel.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_couverture_perimetre import ECARTES, est_ecarte, mesurer_couverture  # noqa: E402


def _ecrire(base: Path, rel: str, contenu: str = "x = 1\n") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding="utf-8")


# --- le critere d'ecartement ------------------------------------------------

def test_ecarte_les_fichiers_de_travail():
    assert est_ecarte("tools/tmp_arxiv_test.py")
    assert est_ecarte("app/tmp_check_dims.py")


def test_ecarte_les_snapshots_de_sauvegarde():
    assert est_ecarte("app/backups/auto_boot_20260319_153549.py")


def test_ecarte_les_fichiers_de_paquet():
    assert est_ecarte("app/__init__.py")
    assert est_ecarte("app/llm/backends/__init__.py")


def test_N_ECARTE_PAS_un_module_interne_a_prefixe_souligne():
    """Piege paye : un critere trop large avait avale 80 modules legitimes."""
    assert not est_ecarte("app/collab_modes/_core.py")
    assert not est_ecarte("app/collab_modes/_arbitration.py")
    assert not est_ecarte("app/_internal/_launch_brain.py")


def test_n_ecarte_pas_un_module_ordinaire():
    assert not est_ecarte("app/forge_rag_engine.py")
    assert not est_ecarte("tools/ci_local.py")


def test_le_critere_est_INSPECTABLE():
    """Un ecartement qu'on ne peut pas relire est un ecartement qu'on ne peut pas contester."""
    assert isinstance(ECARTES, (list, tuple)) and ECARTES
    for regle in ECARTES:
        assert "motif" in regle and regle["motif"], regle


# --- les deux metriques -----------------------------------------------------

def test_le_rapport_porte_son_denominateur_et_ses_ecartes(tmp_path):
    _ecrire(tmp_path, "app/forge_a.py")
    _ecrire(tmp_path, "app/tmp_jetable.py")
    _ecrire(tmp_path, "app/__init__.py", "")
    r = mesurer_couverture(racine=tmp_path)
    assert r["modules_vus"] == 3
    assert r["ecartes"] == 2
    assert r["denominateur"] == 1
    assert len(r["ecartes_nommes"]) == 2, "un ecartement muet surestime la couverture"


def test_les_deux_metriques_sont_SEPAREES(tmp_path):
    """Elles ne doivent jamais etre additionnees ni moyennees en un score unique."""
    _ecrire(tmp_path, "app/forge_a.py")
    _ecrire(tmp_path, "tests/nr/test_forge_a_nr.py", "def test_a():\n    assert 1\n")
    r = mesurer_couverture(racine=tmp_path)
    assert "perimetre_non_vide" in r and "couverture_prouvee" in r
    assert "score" not in r, "aucun score agrege : ce serait la cible que Goodhart vise"
    assert r["perimetre_non_vide"]["n"] == 1


def test_un_test_d_appui_compte_pour_le_perimetre_PAS_pour_la_preuve(tmp_path):
    """C'est tout l'enjeu : un smoke test genere rend le gain mesurable, il ne prouve rien."""
    _ecrire(tmp_path, "app/forge_b.py")
    _ecrire(tmp_path, "tests/nr/test_forge_b_nr.py",
            "# GENERE-APPUI\nimport forge_b\n\n\ndef test_importable():\n    assert forge_b\n")
    r = mesurer_couverture(racine=tmp_path)
    assert r["perimetre_non_vide"]["n"] == 1
    assert r["couverture_prouvee"]["n"] == 0, "un test d'appui genere n'est pas une preuve"


def test_un_test_ecrit_a_la_main_compte_pour_les_deux(tmp_path):
    _ecrire(tmp_path, "app/forge_c.py")
    _ecrire(tmp_path, "tests/nr/test_forge_c_nr.py",
            "import forge_c\n\n\ndef test_comportement():\n    assert forge_c.x == 1\n")
    r = mesurer_couverture(racine=tmp_path)
    assert r["perimetre_non_vide"]["n"] == 1
    assert r["couverture_prouvee"]["n"] == 1


def test_module_sans_aucun_test_ne_compte_nulle_part(tmp_path):
    _ecrire(tmp_path, "app/forge_orphelin.py")
    r = mesurer_couverture(racine=tmp_path)
    assert r["perimetre_non_vide"]["n"] == 0
    assert r["couverture_prouvee"]["n"] == 0
    assert "app/forge_orphelin.py" in r["sans_perimetre"]
