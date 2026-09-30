# -*- coding: utf-8 -*-
"""NR d'EFFET pour les deux outils QA ajoutes le 2026-08-27 -- pas leur import, leur comportement.

Le cliquet `test_nr_coverage_ratchet_nr` exige qu'un nouveau `forge_*.py` soit couvert
par un test NR qui verifie son EFFET. Ces deux outils (recensement de la surface,
matrice de couverture defensive) sont READ-ONLY : on fige ici des comportements
DETERMINISTES, sans dependre du working tree.
"""
import os
import sys

import pytest  # noqa: F401  # marqueur de suite

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_feature_checklist as fc  # noqa: E402
import forge_test_coverage_matrix as cm  # noqa: E402


class TestFeatureChecklistEffet:
    def test_verdicts_a_trois_etats(self):
        # Doctrine Nokido : trois verdicts, jamais deux.
        assert (fc.OK, fc.KO, fc.IND) == ("OK", "KO", "INDETERMINE")

    def test_exclusion_cli_ne_vise_que_les_destructeurs(self):
        # EFFET : la garde d'exclusion --help bloque kill/purge, PAS bench/status
        # (correction du 2026-08-27 : 61 outils rendus mesurables).
        assert fc.DANGEREUX.search("forge_kill_switch")
        assert fc.DANGEREUX.search("forge_purge_rag")
        assert not fc.DANGEREUX.search("forge_bench_rag")
        assert not fc.DANGEREUX.search("forge_status_probe")

    def test_cible_service_resout_le_reel(self):
        # EFFET : un service dont le script existe -> True ; un ${VAR} non resolu -> None.
        assert fc._cible_service({"args": '["tools/forge_feature_checklist.py"]'}) is True
        assert fc._cible_service({"args": '["app/forge_inexistant_xyz.py"]'}) is False
        assert fc._cible_service({"args": '["${PY314}/x.py"]'}) is None


class TestCoverageMatrixEffet:
    def test_dix_couches_quatre_classes(self):
        # EFFET : la matrice couvre exactement les 10 couches du wiki 07 x 4 classes.
        assert len(cm.COUCHES) == 11  # les 10 du wiki 07 + le 6.b (commit gate) distinct
        assert [c for c, _ in cm.CLASSES] == ["injection", "types_json", "limite", "concurrence"]

    def test_markdown_classe_une_matrice_fabriquee(self):
        # EFFET : le rendu compte les trous et nomme la couche, sur une entree figee.
        faux = {
            "classes": ["injection"],
            "cases": 1,
            "trous": 1,
            "lignes": [{"couche": "COUCHE_X", "n_tests": 0, "cells": {"injection": cm.SANS_TEST}}],
        }
        md = cm._markdown(faux)
        assert "COUCHE_X" in md
        assert "1 trous" in md

    def test_etats_exclusifs(self):
        assert cm.COUVERT != cm.DECOUVERT != cm.SANS_TEST
