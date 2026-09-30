"""NR 2026-09-09 — le lecteur JSON rend TROIS etats, et les passeurs ne le recopient plus.

DEUX CHOSES SONT GARDEES ICI, et la seconde compte autant que la premiere.

1. L'INVARIANT. `ABSENT` et `ILLISIBLE` ne sont pas le meme etat, et aucun des deux
   ne vaut « vide ». Un lecteur qui rend `{}` pour les deux fabrique des faux
   negatifs indetectables -- premiere ligne de la constitution semantique du corps.
   L'etat ILLISIBLE porte le TYPE de l'erreur : un echec qui ne se nomme pas doit
   etre re-instruit a chaque fois.

2. LA NON-RECIDIVE DU CLONE. Le 2026-09-09, `forge_generation_inscrire` a ete ecrit
   « sur le patron » de `forge_vitalite_inscrire` -- ce qui, en pratique, voulait
   dire recopier `_lire` (52 noeuds). Le cliquet de clones l'a vu au premier push et
   a casse la CI GitHub (run 34342552425, seul gate rouge sur 16). Le garde avait
   raison. Ce test verifie que les deux passeurs IMPORTENT le lecteur au lieu d'en
   redefinir un : sans lui, le prochain passeur recopiera, et on regelera le socle
   « pour debloquer » -- c'est-a-dire qu'on desarmera le garde au lieu de l'ecouter.

Zero service externe : fichiers en tmp_path, lecture AST du depot.
"""

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_lecture_json as lecteur  # noqa: E402

PASSEURS = ("tools/forge_vitalite_inscrire.py", "tools/forge_generation_inscrire.py")


def test_un_fichier_lisible_est_LU(tmp_path):
    f = tmp_path / "ok.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    donnees, etat = lecteur.lire(f)
    assert etat == "LU"
    assert donnees == {"a": 1}


def test_un_fichier_absent_est_ABSENT_et_pas_vide(tmp_path):
    donnees, etat = lecteur.lire(tmp_path / "jamais_ecrit.json")
    assert etat == "ABSENT", "un fichier qui n'existe pas n'est pas un fichier vide"
    assert donnees == {}


def test_un_fichier_illisible_est_NOMME(tmp_path):
    f = tmp_path / "casse.json"
    f.write_text("{ ceci n est pas du json", encoding="utf-8")
    donnees, etat = lecteur.lire(f)
    assert etat.startswith("ILLISIBLE"), (
        "un JSON casse lu comme ABSENT ou comme vide fait ecraser ce qu'on n'a pas "
        "su lire")
    assert "JSONDecodeError" in etat or "ValueError" in etat, (
        "l'etat doit NOMMER le type d'erreur, sinon il faut le re-instruire a "
        "chaque fois : %s" % etat)
    assert donnees == {}


def test_absent_et_illisible_ne_se_confondent_pas(tmp_path):
    """La distinction est le sujet du module : elle merite son propre temoin."""
    casse = tmp_path / "casse.json"
    casse.write_text("<pas du json>", encoding="utf-8")
    _, etat_absent = lecteur.lire(tmp_path / "rien.json")
    _, etat_illisible = lecteur.lire(casse)
    assert etat_absent != etat_illisible


def test_les_passeurs_importent_le_lecteur_au_lieu_de_le_recopier():
    """Non-recidive du clone qui a casse la CI du 2026-09-09."""
    for rel in PASSEURS:
        src = (RACINE / rel).read_text(encoding="utf-8", errors="replace")
        arbre = ast.parse(src)
        redefinit = [n.name for n in arbre.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name in ("_lire", "lire")]
        assert not redefinit, (
            "%s redefinit %s au lieu d'importer forge_lecture_json : c'est ce clone "
            "exact (52 noeuds) qui a casse le cliquet et la CI GitHub le 2026-09-09"
            % (rel, redefinit))
        importe = any(
            isinstance(n, (ast.Import, ast.ImportFrom))
            and "forge_lecture_json" in ast.unparse(n)
            for n in ast.walk(arbre))
        assert importe, "%s n'importe pas forge_lecture_json" % rel
