"""NR -- une delegation qui ne produit RIEN (0 commit, 0 fichier, aucun artefact pointe) n'est jamais un succes.

Mesure du 2026-10-20 (job_aa2229e3, OPENCODE_GPTOSS) : l'executeur a rendu un DIFF EN TEXTE, tronque a 8000
caracteres -- la ligne finale `{"intent":"OK_DONE","pointer_ref":...}` coupee avec le reste -- et l'effet observe
disait « commits produits : 0 ; fichiers non commites : 0 ». La tache est pourtant sortie done / OK_DONE / SUCCESS :
`_non_livre` ne mord que s'il reste des fichiers NON committes, et aucun autre garde ne regarde le cas « rien du tout ».
DECLARE n'est pas ACHIEVED : un texte sans effet n'est pas une livraison.

Ce qui est garde : 0 commit + 0 fichier + aucun pointer_ref => ok=False et l'effet le DIT (« [RIEN PRODUIT] ») ;
une livraison reelle (un commit) n'est pas touchee.

Correction du 20/10 au soir : la troncature a 8000 caracteres est celle du RESULTAT ENREGISTRE, pas du detail que le juge
a lu. Le garde [AUCUN EFFET] (meme condition, deja present) n'a pas mordu : le juge a donc vu un pointer_ref dans les
180 caracteres perdus. Quel pointeur reste INCONNU ; le trou d'un pointeur `commit:` est garde par
test_juge_pointeur_commit_sans_commit_nr.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
DIFF_TRONQUE = ("## (1) Workflow installation-complete.yml\n\n```diff\n--- a/x\n+++ b/x\n+      - name: Provisionnement\n"
                "...\n\n[TRONQUE -- 8000 caracteres conserves sur 8180 ; 180 NON enregistres.]")


def _module(monkeypatch, effet):
    spec = importlib.util.spec_from_file_location("juge_rien_produit_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_effet_observe", lambda workdir, avant: effet)
    monkeypatch.setattr(m, "_contenu_livre", lambda workdir, avant, autorises=None: None)
    return m


def test_rien_produit_et_aucun_artefact_pointe_n_est_pas_un_succes(monkeypatch, tmp_path):
    m = _module(monkeypatch, "[effet observe] commits produits : 0 (06d8a9d3d..06d8a9d3d) ; fichiers non commites : 0")
    ok, effet, _ = m._juger_livraison(True, DIFF_TRONQUE, str(tmp_path), ("06d8a9d3d", 0))
    assert ok is False, effet
    assert "[RIEN PRODUIT]" in effet


def test_rien_produit_donne_le_verdict_vide(monkeypatch, tmp_path):
    """20/10 soir : « [RIEN PRODUIT] » n'etait pas une marque de `_MARQUES_VIDE`. Comme il passe AVANT le garde
    [AUCUN EFFET] des voies Codex / Vibe / OpenCode, il les court-circuitait : une livraison vide prenait le verdict
    INCONNU au lieu de VIDE. Un seul vocabulaire pour un seul fait."""
    m = _module(monkeypatch, "[effet observe] commits produits : 0 (06d8a9d3d..06d8a9d3d) ; fichiers non commites : 0")
    ok, effet, rendu = m._juger_livraison(True, DIFF_TRONQUE, str(tmp_path), ("06d8a9d3d", 0))
    assert m.verdict_automatique(ok, effet, DIFF_TRONQUE, rendu) == "VIDE", effet


def test_une_livraison_reelle_n_est_pas_touchee(monkeypatch, tmp_path):
    m = _module(monkeypatch, "[effet observe] commits produits : 1 (500cbdf91..93826cfb7) ; fichiers non commites : 0")
    ok, effet, _ = m._juger_livraison(True, "fait : commit 93826cfb7", str(tmp_path), ("500cbdf91", 0))
    assert "[RIEN PRODUIT]" not in effet
