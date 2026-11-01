#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test du cloisonnement d'identité dans resolve_identity.

Vérifie que resolve_identity ne JAMAIS accorde une identité sur le seul 
en-tête nommé par le client sans jeton valide.

Règle de sécurité : en-tête "CLAUDE" + jeton absent ou invalide -> identité non accordée/refus.
                     jeton valide -> identité du jeton, même si l'en-tête dit autre chose.
"""

from __future__ import annotations

import pytest
from typing import Mapping, Optional
from app.forge_videur import resolve_identity


class FakeTokenService:
    """Service de validation de jeton factice pour les tests."""
    
    def __init__(self, valid_tokens: dict[str, str] = None):
        """Initialise avec des tokens valides optionnels.
        
        Args:
            valid_tokens: mapping {nom_agent: token_secret}
        """
        self.valid_tokens = valid_tokens or {}
    
    def validate(self, token: str) -> Optional[str]:
        """Valide un token et retourne l'identité correspondante.
        
        Args:
            token: token à valider
            
        Returns:
            identité de l'agent si token valide, None sinon
        """
        if not token:
            return None
            
        # Recherche si le token correspond à l'un des tokens valides
        for agent_name, secret_token in self.valid_tokens.items():
            if token == secret_token:
                return agent_name
                
        return None


@pytest.fixture
def fake_token_service():
    """Fixture fournissant un FakeTokenService vide par défaut."""
    return FakeTokenService()


@pytest.fixture  
def fake_token_service_with_tokens():
    """Fixture fournissant un FakeTokenService avec des tokens valides."""
    return FakeTokenService({
        "ALICE": "token_alice_secret",
        "BOB": "token_bob_secret", 
        "CLAUDE": "token_claude_secret"
    })


def test_refus_sans_token(fake_token_service):
    """Cas 1: En-tête "CLAUDE" seul, aucun jeton -> refus (anti-spoof)."""
    result = resolve_identity("CLAUDE", "", local=True, agent_tokens={}, 
                             hub_token="", provenance="", 
                             principal_agent_hdr="", declared_agent_hdr="")
    
    # La fonction ne doit JAMAIS accorder l'identité sur le seul en-tête
    # via="header" indique une identité non prouvée (déclarative)
    assert result.get("via") == "header"
    assert result.get("sujet_prouve") == False  # Non prouvé
    assert result.get("ring") >= 4  # Plancher anti-spoof: ring non privilégié


def test_refus_avec_token_invalide(fake_token_service):
    """Cas 2: En-tête "CLAUDE" + token invalide -> refus (anti-spoof)."""
    result = resolve_identity("CLAUDE", "token_invalide", local=True, 
                             agent_tokens={}, hub_token="", provenance="",
                             principal_agent_hdr="", declared_agent_hdr="")
    
    # Token invalide -> via reste "header" (non prouvé)
    assert result.get("via") == "header"
    assert result.get("sujet_prouve") == False  # Non prouvé
    assert result.get("ring") >= 4  # Plancher anti-spoof


def test_identite_du_token_valide(fake_token_service_with_tokens):
    """Cas 3: Token valide -> identité du token, même si l'en-tête dit autre chose."""
    # Le client prétend être "eve" mais le token est celui de "alice"
    result = resolve_identity("eve", "token_alice_secret", local=True,
                             agent_tokens={"ALICE": "token_alice_secret", 
                                         "BOB": "token_bob_secret"},
                             hub_token="", provenance="",
                             principal_agent_hdr="", declared_agent_hdr="")
    
    # L'identité doit être celle du token (ALICE), pas celle de l'en-tête (eve)
    assert result.get("agent") == "ALICE"
    assert result.get("principal") == "ALICE"
    assert result.get("via") == "token"
    assert result.get("sujet_prouve") == True


def test_en_tete_seul_local_dev_mode(fake_token_service):
    """Cas 4: En-tête seul en local avec dev armé -> toujours refus (anti-spoof)."""
    # Même en local, un en-tête seul ne doit jamais accorder un privilège
    result = resolve_identity("CLAUDE", "", local=True, agent_tokens={},
                             hub_token="", provenance="",
                             principal_agent_hdr="", declared_agent_hdr="")
    
    # L'anti-spoof doit plafonner à ring 4 (non-privilégié)
    assert result.get("ring") >= 4
    assert result.get("via") == "header"
    assert result.get("sujet_prouve") == False


def test_reverse_token_sans_header(fake_token_service_with_tokens):
    """Cas 5: Token sans header -> résolution reverse token."""
    # Pas de header, mais token valide -> résolution automatique
    result = resolve_identity("", "token_alice_secret", local=True,
                             agent_tokens={"ALICE": "token_alice_secret"},
                             hub_token="", provenance="",
                             principal_agent_hdr="", declared_agent_hdr="")
    
    # L'identité doit être résolue depuis le token
    assert result.get("agent") == "ALICE"
    assert result.get("sujet_prouve") == True  # le libelle `via` exact n'est pas le contrat


def test_usurpation_par_en_tete_impossible():
    """En-tete CLAUDE sans jeton : ni ring privilegie, ni sujet prouve (TROU : non, mesure 30/10)."""
    # Cas d'usurpation: en-tête CLAUDE sans token qui obtient quand même ring 1
    result = resolve_identity("CLAUDE", "", local=True, agent_tokens={},
                             hub_token="", provenance="",
                             principal_agent_hdr="", declared_agent_hdr="")
    
    assert result.get("ring") >= 4
    assert result.get("sujet_prouve") is not True