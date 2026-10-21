"""NR -- regle d'or « tools » (memoire feedback_validate_tools_payload, docstring 2026-03-22) : un payload d'AGENT sans
outils rend l'agent inerte EN SILENCE ; le format OpenAI des fournisseurs tiers est valide (17/10).

Mesure 17/10 : app/core/payload_validator.py ne validait les tools QUE s'ils etaient presents (un seul appelant,
app/api_facade.py:339) ; `tools=[]` passait ; et un outil au format OpenAI ({"type":"function","function":{...}}) etait
REFUSE (cles MCP name/description/inputSchema exigees) -- brancher le validateur tel quel sur les chemins d'agent aurait
casse des appels sains.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CHEMIN = Path(__file__).resolve().parents[2] / "app" / "core" / "payload_validator.py"


def _validateur():
    if "payload_validator_sous_test" not in sys.modules:
        spec = importlib.util.spec_from_file_location("payload_validator_sous_test", CHEMIN)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        sys.modules["payload_validator_sous_test"] = m
    return sys.modules["payload_validator_sous_test"].PayloadValidator()


MSG = [{"role": "user", "content": "agis"}]
MCP = {"name": "lire", "description": "lit", "inputSchema": {"type": "object", "properties": {}}}
OPENAI = {"type": "function", "function": {"name": "lire", "description": "lit",
                                           "parameters": {"type": "object", "properties": {}}}}


def test_le_format_openai_des_fournisseurs_tiers_est_valide():
    """Isole : echoue sur le FORMAT (cles MCP exigees), pas sur un parametre absent."""
    assert _validateur().validate_payload({"messages": MSG, "tools": [OPENAI]}) == (True, "")


def test_un_payload_d_agent_sans_tools_est_un_agent_inerte():
    ok, err = _validateur().validate_payload({"messages": MSG}, agentique=True)
    assert ok is False and "inerte" in err


def test_une_liste_d_outils_vide_est_un_agent_inerte():
    ok, err = _validateur().validate_payload({"messages": MSG, "tools": []}, agentique=True)
    assert ok is False and "inerte" in err


def test_un_appel_de_texte_sans_tools_reste_sain():
    assert _validateur().validate_payload({"messages": MSG}) == (True, "")


def test_le_format_mcp_reste_valide_en_mode_agentique():
    assert _validateur().validate_payload({"messages": MSG, "tools": [MCP]}, agentique=True) == (True, "")
