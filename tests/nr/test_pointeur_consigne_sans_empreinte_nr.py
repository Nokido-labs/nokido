"""NR -- detection et refus des pointeurs de consigne sans empreinte sha256 (9/11).

Defaut constate : une consigne `consigne:<nom>.txt` sans empreinte `@<sha12>` n'etait
ni resolue ni refusee. L'assignation passait sans consigne (jobs 27d71bd8 et 5b9200e0).
Ce test verifie :
1. un pointeur sans empreinte est refuse avec un message nommant le pointeur et la forme attendue.
2. une description sans pointeur est retournee intacte sans erreur.
3. un pointeur avec empreinte valide est resolu correctement.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

from tools import forge_task_executor  # noqa: E402
from tools.forge_task_executor import servir_consignes_a_l_assignation  # noqa: E402


def test_pointeur_sans_empreinte_refuse_assignation():
    texte = "... consigne:x.txt fin"
    out_desc, err = servir_consignes_a_l_assignation(texte)
    assert err is not None
    assert "consigne:x.txt" in err or "x.txt" in err
    assert "consigne:<nom>@<sha256[:12]>" in err


def test_pointeur_sans_empreinte_md_refuse():
    texte = "description consigne:consigne_test.md reste"
    _, err = servir_consignes_a_l_assignation(texte)
    assert err is not None
    assert "consigne_test.md" in err
    assert "consigne:<nom>@<sha256[:12]>" in err


def test_description_sans_pointeur_retournee_intacte():
    texte = "Tache ordinaire sans consigne particuliere."
    out_desc, err = servir_consignes_a_l_assignation(texte)
    assert err is None
    assert out_desc == texte


def test_pointeur_avec_empreinte_valide_resolu(monkeypatch, tmp_path):
    monkeypatch.setattr(forge_task_executor, "_CONSIGNES_DIR", tmp_path)
    contenu = "Instructions detaillees pour la tache deleguee."
    empreinte = hashlib.sha256(contenu.encode("utf-8")).hexdigest()[:12]
    nom_fichier = "factice.txt"
    (tmp_path / nom_fichier).write_text(contenu, encoding="utf-8")

    texte = f"debut consigne:{nom_fichier}@{empreinte} fin"
    out_desc, err = servir_consignes_a_l_assignation(texte)
    assert err is None
    assert contenu in out_desc
    assert "CONSIGNE RESOLUE (consigne:factice.txt)" in out_desc


def test_description_deja_resolue_repasse_sans_refus(monkeypatch, tmp_path):
    """Reaffectation : une description deja servie porte l'en-tete « (consigne:<nom>) » sans empreinte ;
    ce n'est pas un pointeur, elle ne doit pas etre refusee au second passage."""
    monkeypatch.setattr(forge_task_executor, "_CONSIGNES_DIR", tmp_path)
    contenu = "Consigne servie une fois."
    empreinte = hashlib.sha256(contenu.encode("utf-8")).hexdigest()[:12]
    (tmp_path / "servie.txt").write_text(contenu, encoding="utf-8")
    premier, err1 = servir_consignes_a_l_assignation("tache consigne:servie.txt@%s" % empreinte)
    assert err1 is None
    second, err2 = servir_consignes_a_l_assignation(premier)
    assert err2 is None
    assert second == premier
