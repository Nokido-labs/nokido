# -*- coding: utf-8 -*-
"""Non-regression — la CI locale FERME par un commit, et refuse en le DISANT.

Demande owner du 2026-09-08 : « l'enchainement de verif CI puis du commit puis de la
suite logique doit etre automatique si c'est vert ».

Pourquoi cette fonction vit dans ci_local et pas dans un outil neuf : l'outil qui SAIT
s'il est vert est celui qui doit pouvoir fermer par un commit. Un enchaineur separe
devrait re-deduire le verdict depuis des artefacts, c'est-a-dire refaire la mesure
depuis l'exterieur — exactement le systeme parallele que la discipline de chantier
interdit. `forge_ci_check` regarde la CI GitHub APRES push ; `forge_ci_stop_hook` crie
en fin de tour ; aucun des deux ne couvre « CI locale verte -> commit ».

Le contrat tient en une phrase : on ne commit QUE ce qui a ete MESURE vert, et tout
refus se nomme. En particulier un run PARTIEL (--fast) ne ferme rien — il annonce
lui-meme qu'il ne mesure qu'une fraction, donc son vert ne couvre pas le depot.

Hermetique : fonction pure, aucun git lance, aucun reseau, fichiers en tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ci_local import decider_commit  # noqa: E402


def test_sans_demande_explicite_on_ne_commit_pas():
    """Le defaut est de NE PAS committer : la fermeture s'active, elle ne s'impose pas."""
    ok, motif = decider_commit(sujet=None, fichiers=[], partiel=False, racine=ROOT)
    assert ok is False
    assert "non demand" in motif.lower()


def test_un_run_partiel_ne_ferme_rien(tmp_path):
    """--fast ne mesure qu'une fraction : son vert ne couvre pas le depot."""
    f = tmp_path / "x.py"
    f.write_text("x = 1\n", encoding="utf-8")
    ok, motif = decider_commit(sujet="fix: x", fichiers=["x.py"], partiel=True, racine=tmp_path)
    assert ok is False
    assert "partiel" in motif.lower()


def test_aucun_fichier_nomme_est_un_refus(tmp_path):
    """Jamais de `git add -A` : sans liste explicite, on ne commit pas."""
    ok, motif = decider_commit(sujet="fix: x", fichiers=[], partiel=False, racine=tmp_path)
    assert ok is False
    assert "fichier" in motif.lower()


def test_un_fichier_absent_est_NOMME_dans_le_refus(tmp_path):
    """Un refus qui ne dit pas QUEL fichier manque oblige a re-chercher."""
    (tmp_path / "present.py").write_text("y = 2\n", encoding="utf-8")
    ok, motif = decider_commit(sujet="fix: x",
                               fichiers=["present.py", "fantome.py"],
                               partiel=False, racine=tmp_path)
    assert ok is False
    assert "fantome.py" in motif


def test_cas_nominal_autorise_la_fermeture(tmp_path):
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# b\n", encoding="utf-8")
    ok, motif = decider_commit(sujet="fix(x): sujet court",
                               fichiers=["a.py", "b.md"],
                               partiel=False, racine=tmp_path)
    assert ok is True, motif


# --- niveau integration : le CHEMIN REEL, pas seulement la decision ----------
#
# Paye le 2026-09-08 : `decider_commit` passait ses 6 tests pendant que la CI reelle
# mourait en `NameError: name 'args' is not defined`. La greffe avait ete posee dans
# `_summary` — qui porte le meme texte de conclusion que `main` — ou `args` n'existe
# pas. Un NR qui ne traverse que la fonction pure ne voit RIEN de cela.

def test_summary_traverse_la_fermeture_sans_exploser(monkeypatch):
    """_summary doit accepter les arguments et appeler la fermeture sans lever.

    Sans `args` dans sa signature, l'appel a `_fermeture_si_demandee` levait un
    NameError APRES que tous les gates soient passes : CI verte, rc=1, aucun commit.

    `_INCONCLUS` EST ISOLE, ET C'EST NECESSAIRE. C'est une globale de module : un
    test qui s'execute AVANT celui-ci peut y laisser un gate critique non mesure,
    et `_summary` rend alors 1 -- pour une raison totalement etrangere a ce qu'on
    verifie. Le test passait seul et echouait en groupe, ce qui se lit comme une
    regression du code alors que c'est une dependance a l'ORDRE. Ce test-ci porte
    sur la signature et la fermeture, pas sur la comptabilite des inconclus.
    """
    import ci_local

    monkeypatch.setattr(ci_local, "_INCONCLUS", [])
    # DEUX etats globaux, pas un. Isoler `_INCONCLUS` ne suffisait pas : `_summary`
    # rend aussi 1 quand un domaine CRITIQUE est anergique -- c'est le cas dans une
    # CI complete (archi-lint, sans verdict depuis 15 j), pas quand ce fichier
    # tourne seul. Le test echouait donc UNIQUEMENT en CI, ce qui se lit comme une
    # regression et envoie chercher dans le code.
    monkeypatch.setattr(ci_local, "_anergiques", lambda *a, **k: [])
    # Aucun sujet -> la fermeture doit decliner proprement, pas exploser.
    rc = ci_local._summary([("gate bidon", True)], partiel=False, args=None)
    assert rc == 0


def test_summary_accepte_args_et_ne_commit_pas_sur_run_partiel():
    """Le chemin --fast passe par _summary(partiel=True) : il ne doit rien fermer."""
    import argparse

    import ci_local

    faux = argparse.Namespace(commit_si_vert="fix: ne doit pas passer",
                              commit_fichiers="tools/ci_local.py",
                              commit_corps=None)
    rc = ci_local._summary([("gate bidon", True)], partiel=True, args=faux)
    assert rc == 0


def test_la_signature_de_summary_porte_bien_args():
    """Garde-fou de portee : la greffe doit vivre la ou `args` EXISTE."""
    import inspect

    import ci_local

    params = inspect.signature(ci_local._summary).parameters
    assert "args" in params, "sans ce parametre, _fermeture_si_demandee leve NameError"


def test_un_run_REFERENCE_ne_ferme_rien(tmp_path):
    """Le mode `--reference` juge un sha COMMITE, dans un worktree detache.

    Il l'annonce lui-meme : « l'arbre partage n'entre plus dans le verdict ». Ce
    qui n'est pas commite n'a donc pas ete mesure, et fermer par un commit y
    ajouterait du NON-MESURE -- l'inverse exact du contrat de ce fichier.

    Trouve le 2026-09-14 en verifiant une recommandation avant de l'eriger en
    regle : je m'appretais a conseiller `--reference --commit-si-vert`, qui aurait
    produit un defaut PIRE que le commit manuel qu'il corrigeait. L'enchainement
    juste est en DEUX temps : fermeture en mode ordinaire (qui mesure l'arbre de
    travail), puis `--reference` pour certifier le sha ainsi produit."""
    cible = tmp_path / "x.py"
    cible.write_text("x = 1\n", encoding="utf-8")
    ok, motif = decider_commit(sujet="sujet", fichiers=["x.py"], partiel=False,
                               racine=tmp_path, reference=True)
    assert ok is False, "la fermeture a ete autorisee sur un run reference"
    assert "reference" in motif.lower(), motif
    assert "mesure" in motif.lower(), (
        "le refus doit dire QUE le non-commite n'a pas ete mesure : %s" % motif)


def test_hors_reference_le_cas_nominal_ferme_toujours(tmp_path):
    """CONTRE-EPREUVE : le nouveau refus ne doit pas tout bloquer."""
    cible = tmp_path / "x.py"
    cible.write_text("x = 1\n", encoding="utf-8")
    ok, _motif = decider_commit(sujet="sujet", fichiers=["x.py"], partiel=False,
                                racine=tmp_path, reference=False)
    assert ok is True


def test_un_sujet_vide_ne_passe_pas(tmp_path):
    """Un commit sans sujet est un commit qu'on ne saura pas relire."""
    (tmp_path / "a.py").write_text("a = 1\n", encoding="utf-8")
    ok, motif = decider_commit(sujet="   ", fichiers=["a.py"], partiel=False, racine=tmp_path)
    assert ok is False
    assert "sujet" in motif.lower()
