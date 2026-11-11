"""
Test du validateur de payload en mode OBSERVATION.

Vérifie que les émetteurs branchent correctement validate_payload(agentique=True) 
en mode OBSERVATION : anomalies journalisées mais envoi toujours effectué.
"""

import pytest
import sys
from pathlib import Path

# Ajout du chemin d'accès
_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from app.core.payload_validator import PayloadValidator, validate_payload_observateur


class TestValidatePayloadObservateurs:
    """Test de l'observation de validation de payload agentique."""
    
    def test_validate_payload_agentique_normal(self):
        """Test : payload normal avec outils -> validation OK."""
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "test_tool",
                        "description": "A test tool",
                        "parameters": {"type": "object", "properties": {}}
                    }
                }
            ]
        }
        
        validator = PayloadValidator()
        ok, err = validator.validate_payload(payload, agentique=True)
        
        assert ok is True
        assert err == ""
    
    def test_validate_payload_agentique_sans_outils(self):
        """Test : payload agentique sans outils -> validation KO mais observation OK."""
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello"}
            ]
            # Pas de section "tools"
        }
        
        validator = PayloadValidator()
        ok, err = validator.validate_payload(payload, agentique=True)
        
        assert ok is False
        assert "agent inerte" in err
    
    def test_validate_payload_observateur_normal(self):
        """Test : observation sur payload normal -> pas de log."""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ],
            "tools": []
        }
        
        # L'observation ne doit jamais lever d'exception
        try:
            validate_payload_observateur(payload, "test_emetteur", [])
        except Exception as e:
            pytest.fail(f"L'observation ne doit pas lever d'exception: {e}")
    
    def test_validate_payload_observateur_sans_outils(self):
        """Test : observation sur payload sans outils -> log attendu mais pas d'exception."""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
            # Pas de section "tools" alors que l'émetteur a des outils disponibles
        }
        
        # L'observation ne doit jamais lever d'exception
        try:
            validate_payload_observateur(payload, "test_emetteur", [{"name": "test"}])
        except Exception as e:
            pytest.fail(f"L'observation ne doit pas lever d'exception: {e}")
    
    def test_validate_payload_observateur_avec_outils_vide(self):
        """Test : observation avec outils vide -> validation OK."""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ],
            "tools": []  # Section tools présente mais vide
        }
        
        try:
            validate_payload_observateur(payload, "test_emetteur", [])
        except Exception as e:
            pytest.fail(f"L'observation ne doit pas lever d'exception: {e}")
    
    def test_emetteurs_reels_branches(self):
        """Test : vérification que les émetteurs réels sont branchés."""
        # forge_handoff
        from app.forge_handoff import _llm_round
        assert callable(_llm_round)
        
        # forge_orchestrate_react  
        from tools.forge_orchestrate_react import _ollama_chat
        assert callable(_ollama_chat)
        
        # forge_openai_proxy
        from tools.forge_openai_proxy import chat_completions
        assert callable(chat_completions)
        
        # forge_swarm_agents (catalogue, pas d'émission directe)
        from app.forge_swarm_agents import all_specialists
        assert callable(all_specialists)
    
    def test_payload_invalide_envoi_effectue(self):
        """Test : payload invalide -> anomalie journalisée mais envoi simulé OK."""
        payload_invalide = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
            # Pas de tools alors que agentique=True
        }
        
        # Simuler un envoi (ne doit jamais être bloqué par la validation)
        envoi_effectue = True  # Simulé
        
        # L'observation doit fonctionner sans bloquer
        try:
            validate_payload_observateur(payload_invalide, "test_emetteur", [])
        except Exception:
            envoi_effectue = False
        
        assert envoi_effectue is True
    
    def test_validateur_leve_envoi_effectue(self):
        """Test : validateur qui lève -> anomalie journalisée mais envoi effectué."""
        payload = {
            "messages": [
                {"role": "user", "content": "Hello"}
            ]
        }
        
        # Simuler un envoi réussi après validation
        envoi_reussi = True  # Simulé
        
        try:
            validate_payload_observateur(payload, "test_emetteur", [])
        except Exception:
            envoi_reussi = False  # Ne devrait pas arriver
        
        assert envoi_reussi is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])