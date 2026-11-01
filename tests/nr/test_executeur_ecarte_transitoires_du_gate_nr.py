"""NR -- l'executeur ecarte de ses livraisons TOUT ce que le gate « transitoires » du pre-commit refuse.

Mesure 25/10 : `sandbox/idle_state.json.tmp`, laisse INDEXE par une tache, a fait refuser par le gate les deux
livraisons suivantes de CLAUDE_HEADLESS (eviction, isolation shell) : la liste figee de l'executeur
(`.nokido.agent`, `nokido.lock`) divergeait de la regle du gate (*.tmp, *.lock non legitime...).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402


def test_le_tmp_qui_a_bloque_deux_livraisons_est_ecarte():
    assert T._jamais_livre("sandbox/idle_state.json.tmp")


def test_les_transitoires_historiques_restent_ecartes():
    assert T._jamais_livre(".nokido.agent")
    assert T._jamais_livre("nokido.lock")


def test_la_config_mcp_propre_a_l_executeur_n_est_pas_un_livrable():
    assert T._jamais_livre(".claude_headless_mcp.json")


def test_un_vrai_livrable_et_un_verrou_legitime_passent():
    assert not T._jamais_livre("app/forge_resource_manager.py")
    assert not T._jamais_livre("docs/gouvernance/ISOLATION_SHELL_CODEX_COPILOT_CLINE.md")
    assert not T._jamais_livre("requirements-ci.lock")
