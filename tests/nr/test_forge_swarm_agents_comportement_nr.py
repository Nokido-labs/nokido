import pytest
from app.forge_swarm_agents import specialists_for_use_case, all_specialists

def test_agents_comportement_principal():
    # Comportement principal: instanciation des agents par cas d'usage
    code_agents = specialists_for_use_case("code")
    assert len(code_agents) > 0
    
    # Verification des attributs de base d'un Agent retourne
    for agent in code_agents:
        assert hasattr(agent, "mode")
        assert agent.provider is not None
        assert agent.model is not None
        assert "code" in agent.name or "local" in agent.name

def test_agents_all_specialists():
    # Verifie que tout le catalogue s'instancie sans crasher
    agents = all_specialists()
    assert len(agents) > 0
    
    # Verifie qu'aucun provider interdit n'est present par erreur
    # (le check assert_no_forbidden tourne au load, mais on valide l'etat des instances)
    from app.forge_swarm_agents import FORBIDDEN_PROVIDERS
    for agent in agents:
        assert agent.provider not in FORBIDDEN_PROVIDERS
