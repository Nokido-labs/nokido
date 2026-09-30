# -*- coding: utf-8 -*-
"""Non-regression — le patron des patchs de CRITICAL_FILE tient ses garanties.

Certains fichiers ne peuvent pas passer par `governed_edit` (CRITICAL_FILE, et
`allow_critical` a deja fait tomber le hub le 2026-08-27). Le chemin sur est un
patch git-tracke joue en `trusted_script`. Deux patchs ont ete ecrits sur ce
modele, le second en RECOPIANT le premier — le cliquet de duplication l'a
signale, a raison. Le patron vit maintenant dans `forge_patch_socle`, et ce
fichier verrouille ce qu'il promet.

Chaque garantie ci-dessous protege d'un degat concret : patcher a l'aveugle un
fichier qui a change, doubler un ajout, ecrire du code qui ne compile pas, ou
prendre une cible illisible pour une cible propre.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

S = pytest.importorskip("forge_patch_socle")

ANCRE = "def cible():\n    return 1\n"
AJOUT = "def cible():\n    # MARQUE\n    return 2\n"


def _fichier(tmp_path, contenu: str) -> Path:
    p = tmp_path / "cible.py"
    p.write_text(contenu, encoding="utf-8")
    return p


def test_applique_et_ecrit_un_secours(tmp_path):
    p = _fichier(tmp_path, "x = 0\n" + ANCRE)
    r = S.appliquer(p, ANCRE, AJOUT, "MARQUE", "avant_test", dry_run=False)
    assert r["ok"] and r["modifie"]
    assert "MARQUE" in p.read_text(encoding="utf-8")
    secours = tmp_path / "cible.py.avant_test"
    assert secours.exists() and "MARQUE" not in secours.read_text(encoding="utf-8")


def test_dry_run_n_ecrit_RIEN(tmp_path):
    p = _fichier(tmp_path, ANCRE)
    avant = p.read_text(encoding="utf-8")
    r = S.appliquer(p, ANCRE, AJOUT, "MARQUE", "avant_test", dry_run=True)
    assert r["ok"] and not r["modifie"] and r["dry_run"]
    assert p.read_text(encoding="utf-8") == avant
    assert not (tmp_path / "cible.py.avant_test").exists()


def test_rejouer_est_sans_effet(tmp_path):
    p = _fichier(tmp_path, ANCRE)
    S.appliquer(p, ANCRE, AJOUT, "MARQUE", "avant_test", dry_run=False)
    contenu = p.read_text(encoding="utf-8")
    r = S.appliquer(p, ANCRE, AJOUT, "MARQUE", "avant_test", dry_run=False)
    assert r["ok"] and r.get("deja_applique") and not r["modifie"]
    assert p.read_text(encoding="utf-8") == contenu, "l'ajout a ete double"


def test_ancre_ABSENTE_refuse(tmp_path):
    """Patcher a l'aveugle un fichier qui a change est pire que ne pas patcher."""
    p = _fichier(tmp_path, "rien = 1\n")
    r = S.appliquer(p, ANCRE, AJOUT, "MARQUE", "avant_test", dry_run=False)
    assert not r["ok"] and "ancre" in r["raison"]
    assert p.read_text(encoding="utf-8") == "rien = 1\n"


def test_ancre_AMBIGUE_refuse(tmp_path):
    """Deux occurrences : on ne devine pas laquelle patcher."""
    p = _fichier(tmp_path, ANCRE + "\n" + ANCRE)
    r = S.appliquer(p, ANCRE, AJOUT, "MARQUE", "avant_test", dry_run=False)
    assert not r["ok"] and "2 occurrence" in r["raison"]


def test_un_patch_qui_ne_compile_pas_est_REFUSE(tmp_path):
    """La syntaxe est verifiee sur le resultat COMPLET, avant toute ecriture."""
    p = _fichier(tmp_path, ANCRE)
    r = S.appliquer(p, ANCRE, "def casse(:\n", "MARQUE", "avant_test", dry_run=False)
    assert not r["ok"] and "invalide" in r["raison"]
    assert p.read_text(encoding="utf-8") == ANCRE, "un patch invalide a ete ecrit"


def test_cible_illisible_ne_conclut_pas(tmp_path):
    """Trois etats : applique / deja applique / illisible. Une cible qu'on n'a pas
    pu lire n'est pas une cible propre."""
    r = S.appliquer(tmp_path / "jamais_ecrit.py", ANCRE, AJOUT, "MARQUE",
                    "avant_test", dry_run=True)
    assert not r["ok"] and "illisible" in r["raison"]


def test_rapporter_rend_le_code_de_retour():
    assert S.rapporter({"ok": True, "modifie": True}) == 0
    assert S.rapporter({"ok": False, "raison": "x"}) == 1
