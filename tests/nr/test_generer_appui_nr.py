# -*- coding: utf-8 -*-
"""Non-regression — le generateur de tests d'APPUI ne ment ni sur ce qu'il produit,
ni sur ce qu'il n'a pas pu produire.

Objectif du chantier (owner 2026-09-08) : amener `perimetre non vide` vers 100 %, pour
que `juger_module_avec_gain` puisse se prononcer au lieu de rendre GAIN_INDECIDABLE.
Mesure de depart : 448 modules sur 2272 (19,7 %), 1824 sans aucun perimetre.

TROIS EXIGENCES, chacune adossee a un piege deja paye dans ce depot :

1. **Un test d'appui se DECLARE** (`GENERE-APPUI`). Il compte pour le perimetre, jamais
   pour la couverture PROUVEE. Sans marqueur, il deviendrait indistinguable d'un test
   ecrit a la main et ferait monter les deux metriques d'un coup — Goodhart en une nuit,
   sur la metrique meme que la veille (P1) designe comme la plus dangereuse.

2. **On ne genere que pour un module qui S'IMPORTE VRAIMENT**, sonde en SOUS-PROCESSUS.
   Importer a des effets de bord ici : `forge_goap_hub_bridge` lit le coffre a l'import
   (il ne reassigne plus `sys.stdout` a l'import : c'est fait dans `__main__` depuis le
   2026-09-29), la pile torch meurt en WORKSPACE_GUARD. Generer a l'aveugle casserait
   la suite pure.

3. **Un module non importable est NOMME avec son motif**, jamais avale. C'est une mesure
   en soi : un module du corps qui ne s'importe pas est deja une pathologie. Un
   generateur qui se tait dessus ferait passer une panne pour une absence.

Hermetique : fonctions pures, fichiers en tmp_path, sonde d'import remplacee.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_generer_appui import (  # noqa: E402
    MARQUEUR,
    chemin_test_appui,
    contenu_test_appui,
    generer,
)


def test_le_nom_du_test_derive_du_module():
    assert chemin_test_appui("app/forge_x.py") == "tests/nr/test_appui_forge_x_nr.py"
    assert chemin_test_appui("tools/sous/forge_y.py") == "tests/nr/test_appui_forge_y_nr.py"


def test_le_contenu_porte_le_marqueur_en_TETE():
    """Le lecteur ne scanne que le debut du fichier : le marqueur doit y etre."""
    c = contenu_test_appui("app/forge_x.py")
    assert MARQUEUR in c[:2000]


def test_le_contenu_importe_le_module_et_dit_ce_qu_il_ne_prouve_pas():
    c = contenu_test_appui("app/forge_x.py")
    assert "forge_x" in c
    assert "import" in c
    assert "ne prouve" in c.lower(), "le test doit dire lui-meme sa portee"


def test_ne_genere_pas_si_un_test_existe_deja(tmp_path):
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "forge_x.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_forge_x_nr.py").write_text(
        "def test_a():\n    assert 1\n", encoding="utf-8")
    r = generer(["app/forge_x.py"], racine=tmp_path, sonde=lambda rel, racine: (True, ""),
                appliquer=True)
    assert r["ecrits"] == []
    assert "app/forge_x.py" in r["deja_couverts"]


def test_un_module_non_importable_est_NOMME_avec_son_motif(tmp_path):
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "forge_casse.py").write_text("import nexistepas_zzz\n", encoding="utf-8")
    r = generer(["app/forge_casse.py"], racine=tmp_path,
                sonde=lambda rel, racine: (False, "ModuleNotFoundError: nexistepas_zzz"),
                appliquer=True)
    assert r["ecrits"] == []
    assert any("forge_casse" in k for k in r["non_importables"])
    assert "ModuleNotFoundError" in r["non_importables"]["app/forge_casse.py"]


def test_dry_run_n_ecrit_rien(tmp_path):
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "forge_x.py").write_text("x = 1\n", encoding="utf-8")
    r = generer(["app/forge_x.py"], racine=tmp_path, sonde=lambda rel, racine: (True, ""),
                appliquer=False)
    assert r["ecrits"] == ["tests/nr/test_appui_forge_x_nr.py"]
    assert not (tmp_path / "tests" / "nr" / "test_appui_forge_x_nr.py").exists()


def test_applique_ecrit_un_fichier_valide(tmp_path):
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "forge_x.py").write_text("x = 1\n", encoding="utf-8")
    r = generer(["app/forge_x.py"], racine=tmp_path, sonde=lambda rel, racine: (True, ""),
                appliquer=True)
    p = tmp_path / "tests" / "nr" / "test_appui_forge_x_nr.py"
    assert p.exists()
    compile(p.read_text(encoding="utf-8"), str(p), "exec")  # le fichier doit etre du Python valide
    assert r["ecrits"] == ["tests/nr/test_appui_forge_x_nr.py"]


def test_un_test_genere_QUI_ECHOUE_est_retire_et_nomme(tmp_path):
    """La sonde ne suffit pas : seul le TEST joue fait foi.

    Mesure du 2026-09-08 : la sonde a tourne sous `LaForgeTrusted` et le test sous le
    compte de la CI. `app/brain_ping.py` s'est importe pour l'une (sonde verte) et pas
    pour l'autre (`ModuleNotFoundError: No module named 'zmq'`) — un test genere ROUGE
    est parti dans la suite pure. Deux environnements, deux verdicts : l'instrument
    doit valider dans le contexte OU le test tournera, sinon il fabrique des rouges.
    """
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "forge_x.py").write_text("x = 1\n", encoding="utf-8")
    r = generer(["app/forge_x.py"], racine=tmp_path, sonde=lambda rel, racine: (True, ""),
                appliquer=True, valider=lambda chemin, racine: (False, "ModuleNotFoundError: zmq"))
    assert r["ecrits"] == [], "un test qui echoue ne doit pas rester dans la suite"
    assert not (tmp_path / "tests" / "nr" / "test_appui_forge_x_nr.py").exists()
    assert "app/forge_x.py" in r["non_importables"]
    assert "zmq" in r["non_importables"]["app/forge_x.py"]


def test_un_test_genere_QUI_PASSE_est_conserve(tmp_path):
    (tmp_path / "app").mkdir(parents=True)
    (tmp_path / "app" / "forge_x.py").write_text("x = 1\n", encoding="utf-8")
    r = generer(["app/forge_x.py"], racine=tmp_path, sonde=lambda rel, racine: (True, ""),
                appliquer=True, valider=lambda chemin, racine: (True, ""))
    assert r["ecrits"] == ["tests/nr/test_appui_forge_x_nr.py"]
    assert (tmp_path / "tests" / "nr" / "test_appui_forge_x_nr.py").exists()


def test_le_rapport_porte_son_denominateur(tmp_path):
    (tmp_path / "app").mkdir(parents=True)
    for n in ("a", "b", "c"):
        (tmp_path / "app" / ("forge_%s.py" % n)).write_text("x = 1\n", encoding="utf-8")
    faux = {"app/forge_b.py": (False, "boom")}
    r = generer(["app/forge_a.py", "app/forge_b.py", "app/forge_c.py"], racine=tmp_path,
                sonde=lambda rel, racine: faux.get(rel, (True, "")), appliquer=False)
    assert r["vus"] == 3
    assert len(r["ecrits"]) == 2
    assert len(r["non_importables"]) == 1
