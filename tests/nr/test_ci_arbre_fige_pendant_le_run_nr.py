"""On ne commit que ce qui a ete MESURE — y compris quand l'arbre bouge pendant le run.

LE TROU (releve le 2026-09-14, avant qu'il ne coute). `--commit-si-vert` fait son
`git add` A LA FIN du run, sur les chemins nommes au depart. Entre le debut de la
mesure et ce `add`, il s'ecoule une douzaine de minutes pendant lesquelles l'arbre
de travail est VIVANT : l'agent continue d'editer, et d'autres surfaces partagent
le meme arbre (Claude, Gemini, cowork, taches autonomes).

    t0   les gates mesurent l'etat A
    t1   quelqu'un ecrit l'etat B dans un fichier nomme
    t2   git add <fichier>   ->  c'est B qui part au commit

Le contrat « on ne commit QUE ce qui a ete mesure vert » ne tenait donc que par
chance, tant que personne n'ecrivait pendant le run. C'est precisement la
situation ou l'on se croit protege : le mecanisme existe, il est teste, et son
hypothese silencieuse est fausse.

LA PARADE : une empreinte prise AU DEPART, relue avant le `add`. Elle reutilise la
primitive du domaine (`forge_cycle_verdict.empreinte`, deja deleguee par
`_empreinte_fichier`), qui porte les trois etats.

TROIS ETATS, ET ILS NE SE FONDENT PAS :

    bouge         l'empreinte a change -> ce serait commiter du non-mesure
    indetermine   une des deux lectures est ILLISIBLE -> on ne peut PAS conclure
                  a l'identite, donc on ne ferme pas non plus
    identique     seul cas ou la fermeture reste legitime

Deux `ILLISIBLE` ne prouvent pas l'egalite : c'est la meme regle qu'a la
comparaison de contexte, et la docstring de la primitive le dit — « une empreinte
vide comparee a une empreinte vide serait identique : le garde s'ouvrirait
exactement quand il ne peut pas voir ».
"""

from __future__ import annotations

import pathlib
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def ci():
    try:
        import ci_local
    except Exception as exc:  # noqa: BLE001
        pytest.fail("ci_local ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return ci_local


# --------------------------------------------------------------------------
# L'empreinte de depart, et sa relecture
# --------------------------------------------------------------------------

def test_un_fichier_inchange_reste_fermable(ci, tmp_path):
    """CONTRE-EPREUVE d'abord : sans elle, tout refuser passerait les suivants."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    avant = ci.empreintes_fermeture(["a.py"], tmp_path)
    bouges, indetermines = ci.fermeture_encore_valide(avant, tmp_path)
    assert bouges == [] and indetermines == []


def test_un_fichier_MODIFIE_pendant_le_run_est_detecte(ci, tmp_path):
    """LE cas : l'agent edite entre la mesure et le `git add`."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    avant = ci.empreintes_fermeture(["a.py"], tmp_path)
    (tmp_path / "a.py").write_text("x = 2  # ecrit PENDANT le run\n", encoding="utf-8")
    bouges, indetermines = ci.fermeture_encore_valide(avant, tmp_path)
    assert bouges == ["a.py"], (bouges, indetermines)
    assert indetermines == []


def test_un_fichier_SUPPRIME_pendant_le_run_est_detecte(ci, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    avant = ci.empreintes_fermeture(["a.py"], tmp_path)
    (tmp_path / "a.py").unlink()
    bouges, _ind = ci.fermeture_encore_valide(avant, tmp_path)
    assert bouges == ["a.py"]


def test_un_chemin_ILLISIBLE_est_INDETERMINE_jamais_identique(ci, tmp_path):
    """De deux lectures refusees on ne conclut NI a l'identite NI a la difference.

    Un dossier ouvert en lecture binaire leve OSError : la primitive rend
    `ILLISIBLE:<type>` des deux cotes. Les declarer egaux ouvrirait le garde
    exactement quand il est aveugle."""
    (tmp_path / "dossier").mkdir()
    avant = ci.empreintes_fermeture(["dossier"], tmp_path)
    bouges, indetermines = ci.fermeture_encore_valide(avant, tmp_path)
    assert indetermines == ["dossier"], (bouges, indetermines)
    assert bouges == [], "un illisible n'est pas une modification MESUREE"


# --------------------------------------------------------------------------
# La decision : la fermeture refuse, et NOMME
# --------------------------------------------------------------------------

def test_la_fermeture_REFUSE_si_un_fichier_a_bouge(ci, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    ok, motif = ci.decider_commit(sujet="fix: x", fichiers=["a.py"], partiel=False,
                                  racine=tmp_path, bouges=["a.py"])
    assert ok is False
    assert "a.py" in motif, "le fichier fautif doit etre NOMME : %s" % motif
    assert "mesure" in motif.lower(), motif


def test_la_fermeture_REFUSE_sur_un_INDETERMINE(ci, tmp_path):
    """Ne pas fermer sur ce qu'on n'a pas pu verifier -- et le dire autrement
    qu'une modification, sinon on envoie chercher un changement qui n'existe
    peut-etre pas."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    ok, motif = ci.decider_commit(sujet="fix: x", fichiers=["a.py"], partiel=False,
                                  racine=tmp_path, indetermines=["a.py"])
    assert ok is False
    bas = motif.lower()
    assert "a.py" in motif, motif
    assert "verifi" in bas or "indetermine" in bas, motif


def test_sans_ecart_la_fermeture_reste_autorisee(ci, tmp_path):
    """CONTRE-EPREUVE de la decision : le nouveau refus ne bloque pas tout."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    ok, _motif = ci.decider_commit(sujet="fix: x", fichiers=["a.py"], partiel=False,
                                   racine=tmp_path)
    assert ok is True


# --------------------------------------------------------------------------
# LE CHEMIN REEL -- une decision juste sur un cablage absent ne protege rien
# --------------------------------------------------------------------------

def _faux_args(**kw):
    from types import SimpleNamespace
    base = {"commit_si_vert": "fix: x", "commit_fichiers": "a.py",
            "commit_corps": None, "reference": None}
    base.update(kw)
    return SimpleNamespace(**base)


def test_le_chemin_REEL_refuse_quand_un_fichier_a_bouge(ci, tmp_path, monkeypatch,
                                                        capsys):
    """`_fermeture_si_demandee` est ce que la production appelle.

    Eprouver `decider_commit` seul prouverait qu'on SAIT refuser, pas que le refus
    ARRIVE : c'est la difference qui a coute un `--check` mort en NameError
    pendant que `check()` passait ses tests."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "_EMPREINTES_FERMETURE",
                        ci.empreintes_fermeture(["a.py"], tmp_path))
    (tmp_path / "a.py").write_text("x = 2  # PENDANT le run\n", encoding="utf-8")

    commits = []
    monkeypatch.setattr(ci, "_fermer_par_commit",
                        lambda *a, **k: commits.append(a))
    ci._fermeture_si_demandee(_faux_args(), False)

    assert not commits, "la fermeture a commite un fichier modifie pendant le run"
    sortie = capsys.readouterr().out
    assert "a.py" in sortie, "le refus doit NOMMER le fichier : %s" % sortie[-300:]


def test_le_chemin_REEL_ferme_TOUJOURS_quand_rien_n_a_bouge(ci, tmp_path,
                                                            monkeypatch, capsys):
    """CONTRE-EPREUVE du cablage : sans elle, un garde trop large passerait."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    monkeypatch.setattr(ci, "_EMPREINTES_FERMETURE",
                        ci.empreintes_fermeture(["a.py"], tmp_path))
    commits = []
    monkeypatch.setattr(ci, "_fermer_par_commit",
                        lambda *a, **k: commits.append(a))
    ci._fermeture_si_demandee(_faux_args(), False)
    assert commits, "la fermeture legitime n'a pas eu lieu : %s" % (
        capsys.readouterr().out[-300:])
