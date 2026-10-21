"""NR -- sans aucun commit produit, un pointeur de COMMIT ne designe pas la livraison de la tache (20/10).

Trou lu dans le code le 20/10 en instruisant job_aa2229e3 (OPENCODE_GPTOSS, sorti done / OK_DONE avec 0 commit et
0 fichier) : un `pointer_ref` a schema (`commit:<sha> ...`, souvent recopie de la tache elle-meme) echappe a
`_artefact_declare_absent` et `_artefact_non_produit` (pointeur « d'un autre registre »), et `_rien_produit` comme le
garde [AUCUN EFFET] exemptent toute reponse qui porte un pointer_ref. Si ce fut le cas exact de job_aa2229e3 est
INCONNU (les 180 derniers caracteres de sa reponse n'ont pas ete enregistres) ; le trou, lui, est mesure ici.

Garde : 0 commit + 0 fichier + pointeur `commit:<sha>` ou `<branche>@<sha>` => [RIEN PRODUIT]. Un pointeur `bb:` reste
legitime sans fichier (un fait au tableau noir est un effet).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
VIDE = "[effet observe] commits produits : 0 (06d8a9d3d..06d8a9d3d) ; fichiers non commites : 0"


def _module(monkeypatch):
    spec = importlib.util.spec_from_file_location("juge_pointeur_commit_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: VIDE)
    monkeypatch.setattr(m, "_contenu_livre", lambda workdir, avant, autorises=None: None)
    return m


def _reponse(pointeur):
    return 'fait.\n{"intent":"OK_DONE","pointer_ref":"%s"}' % pointeur


@pytest.mark.parametrize("pointeur", ["commit:f00e3ba35 tests/nr/test_ci_chiffrement_provisionne_nr.py",
                                      "agent/opencode@f00e3ba35"])
def test_un_pointeur_de_commit_sans_commit_produit_n_est_pas_livre(monkeypatch, tmp_path, pointeur):
    m = _module(monkeypatch)
    ok, effet, _ = m._juger_livraison(True, _reponse(pointeur), str(tmp_path), ("06d8a9d3d", 0))
    assert ok is False and "[RIEN PRODUIT]" in effet, effet


def test_un_fait_au_tableau_noir_reste_une_livraison(monkeypatch, tmp_path):
    m = _module(monkeypatch)
    ok, effet, _ = m._juger_livraison(True, _reponse("bb:architecture_rules/NEXT_essai"), str(tmp_path),
                                      ("06d8a9d3d", 0))
    assert "[RIEN PRODUIT]" not in effet, effet
