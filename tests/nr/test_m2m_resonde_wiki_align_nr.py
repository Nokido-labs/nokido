# -*- coding: utf-8 -*-
"""NR d'EFFET pour les deux outils ajoutes le 2026-08-27 : forge_resonde_trusted et
forge_wiki_align. Comportements deterministes, sans I/O ni compte, sans LLM."""
import os
import re
import sys

import pytest  # noqa: F401  # marqueur de suite

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_resonde_trusted as rt  # noqa: E402
import forge_wiki_align as wa  # noqa: E402


class TestResondeTrusted:
    def test_resoudre_variante_et_sans_prefixe(self):
        # EFFET : un nom de doc resout vers la variante reelle (mcts->mcts_engine) ou
        # le fichier sans prefixe (forge_brain_worker->brain_worker).
        chemins = {
            "forge_mcts_engine": r"/x/forge_mcts_engine.py",
            "brain_worker": r"/y/brain_worker.py",
        }
        assert rt._resoudre("forge_mcts", chemins) == r"/x/forge_mcts_engine.py"
        assert rt._resoudre("forge_brain_worker", chemins) == r"/y/brain_worker.py"
        assert rt._resoudre("forge_inexistant_xyz", chemins) is None

    def test_filtres_hors_perimetre(self):
        # EFFET : les capacites deportees et les modules lourds sont ecartes du resonde.
        assert rt._DEPORTE.search("recon_scan")
        assert rt._LOURD.search("forge_ami_train_cycle")
        assert not rt._DEPORTE.search("forge_trace_sidecar")


class TestWikiAlign:
    def test_table_renommages_surs(self):
        assert wa.TABLE.get("forge_mcts") == "forge_mcts_engine"
        assert wa.TABLE.get("forge_brain_worker") == "brain_worker"

    def test_remplacement_sans_double(self):
        # EFFET : \b + lookahead -> forge_mcts remplace, mais forge_mcts_engine intact.
        motif = re.compile(r"\bforge_mcts(?!\w)")
        assert motif.sub("forge_mcts_engine", "voir forge_mcts ici") == "voir forge_mcts_engine ici"
        assert motif.sub("forge_mcts_engine", "forge_mcts_engine reste") == "forge_mcts_engine reste"
