# -*- coding: utf-8 -*-
"""sandbox/hybrid_state_machine.py — Machine à états souveraine et résiliente pour Nokido/LaForge.

Implémente la chorégraphie de routage sémantique NPU, query condensation et auto-correction 
d'erreurs avec Claude en Python pur (sans dépendance externe LangGraph).
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("hybrid_state_machine")

THRESHOLD = 0.45  # Seuil de similarité cosinus locale (Golden Rule)


class AgentState(BaseModel):
    """
    État transactionnel de la session utilisateur.
    Utilise Pydantic pour valider à l'exécution les types injectés par le LLM.
    """
    query: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    condensed_query: Optional[str] = None
    intent: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    local_execution_result: Optional[str] = None
    local_execution_error: Optional[str] = None
    last_tool_use_id: Optional[str] = None
    retry_count: int = 0
    status: str = "PENDING"  # PENDING | SUCCESS | FAILED

    def add_history(self, role: str, content: Any) -> None:
        """Ajoute de nouveaux messages à l'historique."""
        self.history.append({"role": role, "content": content})


class HybridStateMachine:
    """
    Orchestrateur déterministe en Python pur de la machine à états hybride.
    Gère la condensation, le filtrage local, et la boucle de rétroaction d'erreurs.
    """

    def __init__(self, local_llm_fn=None, embed_router_fn=None, claude_fn=None, local_executor_fn=None):
        self.local_llm_fn = local_llm_fn
        self.embed_router_fn = embed_router_fn
        self.claude_fn = claude_fn
        self.local_executor_fn = local_executor_fn

    def run(self, initial_query: str, history: Optional[list[dict[str, Any]]] = None) -> AgentState:
        """
        Exécute la machine à états sur la requête utilisateur.
        """
        state = AgentState(query=initial_query, history=history or [])
        
        # 1. Condensation de la requête (Multi-tours)
        state = self._condense_query(state)
        
        # 2. Filtrage par Routeur Sémantique local (0 Token Cloud)
        state = self._route_locally(state)
        
        # Si le routeur sémantique n'a pas trouvé d'intention fiable, on sollicite Claude
        if not state.intent:
            state = self._call_llm_for_extraction(state)
            if not state.intent:
                state.status = "FAILED"
                return state

        # 3. Boucle d'exécution locale et de résilience (auto-correction)
        # On autorise 3 tentatives d'exécution locale (initiale + 2 corrections)
        for attempt in range(3):
            state = self._execute_local_workflow(state)
            
            # S'il n'y a pas d'erreur, l'exécution est réussie
            if not state.local_execution_error:
                state.status = "SUCCESS"
                return state
                
            # Si on a atteint la limite d'essais (2 retries max), on arrête
            if attempt == 2:
                break
                
            # Sinon, on tente une rétroaction d'erreur vers Claude
            logger.warning(
                f"[Résilience] Échec de l'exécution locale (tentative {attempt + 1}/3). "
                f"Erreur : {state.local_execution_error}. Rétroaction vers Claude."
            )
            state = self._call_llm_for_extraction(state)
            
            # Si l'extraction de Claude échoue à renvoyer une intention, on s'arrête
            if not state.intent:
                break

        state.status = "FAILED"
        return state

    def _condense_query(self, state: AgentState) -> AgentState:
        """
        Étape 1 : Query Condenser.
        Condense la requête utilisateur si un historique existe pour préserver le contexte.
        Purge également les variables résiduelles de la transaction précédente.
        """
        condensed = state.query
        if state.history and self.local_llm_fn:
            try:
                condensed = self.local_llm_fn(state.query, state.history)
            except Exception as e:
                logger.error(f"Erreur lors de la condensation de requête locale : {e}")

        # Reset des champs de la transaction N-1
        state.condensed_query = condensed
        state.intent = None
        state.parameters = {}
        state.local_execution_result = None
        state.local_execution_error = None
        state.status = "PENDING"
        return state

    def _route_locally(self, state: AgentState) -> AgentState:
        """
        Étape 2 : Similarité locale.
        Utilise le routeur sémantique BGE-M3 (local NPU XDNA) pour chercher une correspondance.
        Filtre strictement selon un SEUIL de similarité (THRESHOLD).
        """
        if self.embed_router_fn:
            try:
                intent, score = self.embed_router_fn(state.condensed_query)
                if intent and score >= THRESHOLD:
                    state.intent = intent
                    logger.info(f"[Routeur Local] Intention captée sémantiquement : '{intent}' (score: {score})")
                else:
                    logger.info(f"[Routeur Local] Score sémantique trop faible ({score} < {THRESHOLD}), fallback vers Claude.")
            except Exception as e:
                logger.error(f"Erreur lors du routage sémantique local : {e}")
        return state

    def _call_llm_for_extraction(self, state: AgentState) -> AgentState:
        """
        Étape 3 : Triage/Extraction LLM (Claude).
        Persiste chaque tour d'erreur dans state.history pour que la rétroaction
        conserve la séquence historique complète (assistant + tool_result + is_error=True).
        """
        if not self.claude_fn:
            state.local_execution_error = "Erreur fatale : Service d'extraction Claude indisponible."
            return state

        # Si nous avons une erreur d'exécution locale précédente, on persiste le tour en erreur dans history
        if state.local_execution_error and state.last_tool_use_id:
            # 1. On stocke la tentative d'appel d'outil défectueux de Claude
            state.add_history("assistant", [
                {
                    "type": "tool_use",
                    "id": state.last_tool_use_id,
                    "name": state.intent,
                    "input": state.parameters
                }
            ])
            # 2. On stocke la réponse d'erreur de l'outil avec le flag is_error=True
            state.add_history("user", [
                {
                    "type": "tool_result",
                    "tool_use_id": state.last_tool_use_id,
                    "is_error": True,
                    "content": state.local_execution_error
                }
            ])
            # Reset de l'erreur brute puisqu'elle est historisée dans state.history
            state.local_execution_error = None

        # Reconstitution du payload messages complet à partir de state.history + requête courante
        messages = list(state.history)
        messages.append({"role": "user", "content": state.condensed_query})

        # Invocation du LLM
        try:
            extraction = self.claude_fn(messages)
            state.intent = extraction.get("intent")
            state.parameters = extraction.get("parameters") or {}
            state.last_tool_use_id = extraction.get("tool_use_id")
            state.retry_count += 1
        except Exception as e:
            state.local_execution_error = f"Erreur lors de l'extraction Claude : {e}"
            
        return state

    def _execute_local_workflow(self, state: AgentState) -> AgentState:
        """
        Étape 4 : Exécution locale.
        Exécute le workflow localement et capture l'erreur en cas d'exception.
        """
        if not self.local_executor_fn:
            state.local_execution_error = "Erreur fatale : Exécuteur local indisponible."
            return state
            
        try:
            result = self.local_executor_fn(state.intent, state.parameters)
            state.local_execution_result = result
            state.local_execution_error = None
        except Exception as e:
            state.local_execution_error = f"{type(e).__name__}: {str(e)}"
            
        return state
