"""NR -- un commit d'executeur REFUSE par le scorecard n'est pas une livraison reussie (20/10).

Mesure 20/10 (job_2a6a27b3, MISTRAL, codestral) : Vibe modifie tools/forge_memory_consolidator.py, le code ne compile
pas (ligne 173), `_committer_pour_agent` voit le scorecard REFUSER le commit (« det-diff: ne compile pas ») et le dit
dans le detail -- mais la reponse pointe le fichier (`pointer_ref`), ce qui exempte `_non_livre`, et le fichier,
modifie, echappe a `_artefact_non_produit`. Resultat : « VIBE OK », tache done. Un refus du scorecard est un ECHEC
NOMME, quel que soit le pointeur.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
EFFET = "[effet observe] commits produits : 0 (384556b93..384556b93) ; fichiers non commites : 1"
DETAIL = ('{"intent": "OK_DONE", "pointer_ref": "tools/forge_memory_consolidator.py"}\n'
          "[executeur] commit executeur REFUSE par le scorecard : det-diff: ne compile pas -- "
          "tools/forge_memory_consolidator.py:173 invalid syntax")


def _module(monkeypatch):
    spec = importlib.util.spec_from_file_location("juge_scorecard_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: EFFET)
    monkeypatch.setattr(m, "_contenu_livre", lambda workdir, avant, autorises=None: None)
    monkeypatch.setattr(m, "_artefact_declare_absent", lambda reponse, workdir: None)
    monkeypatch.setattr(m, "_artefact_non_produit", lambda reponse, workdir, avant: None)
    return m


def test_un_refus_du_scorecard_n_est_pas_un_succes(monkeypatch, tmp_path):
    m = _module(monkeypatch)
    ok, effet, _ = m._juger_livraison(True, DETAIL, str(tmp_path), ("384556b93", 0))
    assert ok is False and "[SCORECARD REFUSE]" in effet, effet


def test_sans_refus_le_juge_ne_change_rien(monkeypatch, tmp_path):
    m = _module(monkeypatch)
    monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: EFFET.replace("produits : 0", "produits : 1"))
    ok, effet, _ = m._juger_livraison(True, DETAIL.split("\n")[0], str(tmp_path), ("384556b93", 0))
    assert "[SCORECARD REFUSE]" not in effet, effet
