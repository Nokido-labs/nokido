# -*- coding: utf-8 -*-
"""tests/test_hybrid_state_machine.py — Tests de la machine à états hybride et de l'auto-correction.
"""

from __future__ import annotations

import pytest
from sandbox.hybrid_state_machine import HybridStateMachine, AgentState, THRESHOLD


def test_state_machine_nominal_local_route():
    """ Test du chemin de similarité locale (0 Token Cloud) avec score supérieur au seuil """
    def mock_embed_router(query):
        if "rembours" in query:
            return "trigger_refund_workflow", THRESHOLD + 0.1
        return None, 0.0

    def mock_executor(intent, params):
        if intent == "trigger_refund_workflow":
            return "Remboursement traité avec succès."
        raise ValueError("Intention inconnue")

    machine = HybridStateMachine(
        embed_router_fn=mock_embed_router,
        local_executor_fn=mock_executor
    )

    state = machine.run(initial_query="Je veux être remboursé")

    assert state.intent == "trigger_refund_workflow"
    assert state.local_execution_result == "Remboursement traité avec succès."
    assert state.local_execution_error is None
    assert state.status == "SUCCESS"
    assert state.retry_count == 0


def test_state_machine_local_route_under_threshold():
    """ Test qu'une similarité locale inférieure au seuil bascule vers Claude """
    calls_count = 0

    def mock_embed_router(query):
        # Score de 0.35, inférieur au seuil requis
        return "trigger_refund_workflow", THRESHOLD - 0.1

    def mock_claude(messages):
        nonlocal calls_count
        calls_count += 1
        return {
            "intent": "trigger_refund_workflow",
            "parameters": {"user_id": 123, "amount": 10},
            "tool_use_id": "toolu_fake_id_under"
        }

    def mock_executor(intent, params):
        return "Action traitée."

    machine = HybridStateMachine(
        embed_router_fn=mock_embed_router,
        claude_fn=mock_claude,
        local_executor_fn=mock_executor
    )

    state = machine.run(initial_query="Rembourse-moi")

    assert state.intent == "trigger_refund_workflow"
    assert state.retry_count == 1  # Claude a bien été sollicité à cause du score trop faible
    assert state.status == "SUCCESS"


def test_state_machine_query_rewriting():
    """ Test de la condensation de requête (multi-tours) """
    history = [
        {"role": "user", "content": "Génère un rapport de ventes."},
        {"role": "assistant", "content": "Rapport généré."}
    ]

    def mock_condenser(query, hist):
        if "mail" in query and "rapport" in hist[0]["content"]:
            return "Envoie le rapport de ventes par mail"
        return query

    def mock_embed_router(query):
        if "rapport de ventes par mail" in query:
            return "send_email_workflow", THRESHOLD + 0.15
        return None, 0.0

    def mock_executor(intent, params):
        return "Email envoyé."

    machine = HybridStateMachine(
        local_llm_fn=mock_condenser,
        embed_router_fn=mock_embed_router,
        local_executor_fn=mock_executor
    )

    state = machine.run(initial_query="Envoie-le par mail", history=history)

    assert state.condensed_query == "Envoie le rapport de ventes par mail"
    assert state.intent == "send_email_workflow"
    assert state.local_execution_result == "Email envoyé."
    assert state.status == "SUCCESS"
    assert state.retry_count == 0


def test_state_machine_claude_extraction_and_self_correction_cumulative():
    """ Test du triage LLM avec boucle de résilience et persistance cumulative de l'historique """
    calls_count = 0

    def mock_claude(messages):
        nonlocal calls_count
        calls_count += 1
        
        # 1er appel : Claude fait une erreur
        if calls_count == 1:
            return {
                "intent": "trigger_refund_workflow",
                "parameters": {"user_id": 123, "amount": -10},
                "tool_use_id": "toolu_fake_id_1"
            }
        
        # 2e appel : Claude fait une autre erreur de type
        if calls_count == 2:
            # Vérification de l'historique cumulé : le message précédent (assistant + tool_result) doit être dans messages
            assert len(messages) == 3  # [Assistant_toolu_1, User_tool_result_1, User_query]
            assert messages[0]["role"] == "assistant"
            assert messages[1]["role"] == "user"
            assert messages[1]["content"][0]["tool_use_id"] == "toolu_fake_id_1"

            return {
                "intent": "trigger_refund_workflow",
                "parameters": {"user_id": 123, "amount": "gratuit"},
                "tool_use_id": "toolu_fake_id_2"
            }

        # 3e appel : Claude corrige et renvoie les bons paramètres
        if calls_count == 3:
            # Vérification de l'historique cumulé
            assert len(messages) == 5  # [Ass_1, User_res_1, Ass_2, User_res_2, User_query]
            assert messages[2]["content"][0]["id"] == "toolu_fake_id_2"
            assert messages[3]["content"][0]["tool_use_id"] == "toolu_fake_id_2"

            return {
                "intent": "trigger_refund_workflow",
                "parameters": {"user_id": 123, "amount": 10},
                "tool_use_id": "toolu_fake_id_3"
            }

        return {}

    def mock_executor(intent, params):
        amount = params.get("amount")
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError(f"ValidationError: Le montant '{amount}' est invalide.")
        return f"Remboursement de {amount}€ effectué."

    machine = HybridStateMachine(
        claude_fn=mock_claude,
        local_executor_fn=mock_executor
    )

    state = machine.run(initial_query="Je veux rembourser 10€")

    assert state.local_execution_result == "Remboursement de 10€ effectué."
    assert state.local_execution_error is None
    assert state.retry_count == 3  # 1er appel + 2 retries d'auto-correction
    assert state.status == "SUCCESS"


def test_state_machine_terminal_failed():
    """ Test que la machine à états s'arrête en FAILED après 3 échecs persistants """
    def mock_claude(messages):
        return {
            "intent": "trigger_refund_workflow",
            "parameters": {"amount": -100},
            "tool_use_id": "toolu_persistent_error"
        }

    def mock_executor(intent, params):
        # L'exécuteur échouera systématiquement
        raise ValueError("Erreur critique persistante.")

    machine = HybridStateMachine(
        claude_fn=mock_claude,
        local_executor_fn=mock_executor
    )

    state = machine.run(initial_query="Je veux rembourser")

    assert state.status == "FAILED"
    assert state.local_execution_error == "ValueError: Erreur critique persistante."
    assert state.retry_count == 3
