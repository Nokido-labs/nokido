"""Garde anti-regression : routage M2M vers AGY (identite canonique antigravity).

Cause historique : notify/task.assign visaient agt_agy (inbox jamais drainee)
au lieu de agt_antigravity (canal reel d'AGY, 46 messages lus). Ce test verrouille
les deux corrections dans app/forge_mcp_registry.py.
"""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parent.parent
       / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")


def test_to_map_has_antigravity_aliases():
    for alias in ('"ANTIGRAVITY": "agt_antigravity"', '"AGY": "agt_antigravity"',
                  '"antigravity": "agt_antigravity"', '"agy": "agt_antigravity"'):
        assert alias in SRC, f"alias notify manquant: {alias}"


def test_task_assign_canonicalises_agy():
    assert 'if ag_raw in ("AGY", "ANTIGRAVITY"):' in SRC
    assert 'ag_raw = "ANTIGRAVITY"' in SRC


def test_no_orphan_agt_agy_literal():
    # aucun code ne doit produire/cibler l'inbox fantome agt_agy
    assert "agt_agy" not in SRC
