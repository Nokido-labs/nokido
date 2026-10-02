import pytest
import asyncio
import sys
import importlib
from pathlib import Path

def test_debate_comportement_synth(monkeypatch):
    # Import du module
    import tools.forge_swarm_debate as debate
    
    # Mock du comportement de ask (proxy LLM)
    async def mock_ask(prov, prompt, max_tokens, rag_context):
        return {"text": f"MOCK_SYNTHESIS_FOR_{prov}", "ok": True}
    
    # Patch de la fonction ask
    import nokido_agent.app.forge_agent_proxy
    monkeypatch.setattr(nokido_agent.app.forge_agent_proxy, "ask", mock_ask)
    
    answers = [
        ("Role A", "groq", "Reponse A", True),
        ("Role B", "mistral", "Reponse B", True)
    ]
    
    # Test de la fonction de synthese
    res = asyncio.run(debate._synth(answers, "Fais une synthese"))
    assert "MOCK_SYNTHESIS_FOR_groq" in res

@pytest.mark.asyncio
async def test_debate_comportement_round(monkeypatch):
    import tools.forge_swarm_debate as debate
    
    # Test qu'un round lance bien N taches et filtre les reussites
    async def mock_ask_one(role, prov, task):
        # On simule qu'un echoue et un reussit
        if prov == "groq":
            return (role, prov, "success", True)
        return (role, prov, "timeout", False)
        
    monkeypatch.setattr(debate, "_ask_one", mock_ask_one)
    
    # Temporairement on reduit les specialistes pour le test
    old_specialists = debate.SPECIALISTS
    debate.SPECIALISTS = [("Role1", "groq"), ("Role2", "mistral")]
    
    try:
        res = await debate._round("task", "R1")
        # Seul groq devrait etre dans le resultat final car ok=True
        assert len(res) == 1
        assert res[0][1] == "groq"
    finally:
        debate.SPECIALISTS = old_specialists
