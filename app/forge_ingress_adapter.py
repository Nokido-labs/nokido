from __future__ import annotations

__FORGE_COLOR__ = "digestif/ingest : adaptateur d'entree"  # organe declare le 2026-09-06 (audit de raccordement)

# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-06-10 | VER:v1.0
#FORGE:[score:95|agent:agt_gemini|temp:0.00|risk:0.10|ast:OK|test:PENDING|color:GREEN]
Ingress Adapter — Middleware de qualification sémantique et déterministe.
==============================================================================
Implémente le triptyque de sécurité : [Identité CLI] + [Destination] + [Tâche].
Injecte un Ring de Session variable pour confiner les modèles Cloud en Ring 4.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from nokido_agent.app.forge_integrity import IntegrityRing, is_at_least

logger = logging.getLogger("forge.ingress")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration du Confinement
# ─────────────────────────────────────────────────────────────────────────────

# Outils autorisés en Ring 4 (Confinement Cloud / Read-Only)
# Ces outils ne mutent pas le système et ne permettent pas d'exécution.
RING_4_ALLOWLIST = {
    "read",
    "read_function_body",
    "get_file_skeleton",
    "get_function_dependencies",
    "rag",
    "query",
    "whoami",
    "list_providers",
    "quota_status",
    "search_recent",
    "poll",
    "biblio",
}

# Providers considérés comme "Cloud" (Zero-Trust)
CLOUD_PROVIDERS = {
    "groq",
    "anthropic",
    "google",
    "openai",
    "mistral",
    "openrouter",
    "sambanova",
    "cerebras",
    "nvidia",
    "hf",
}

# Providers considérés comme "Locaux" (Souverains)
LOCAL_PROVIDERS = {
    "ollama",
    "llamacpp",
    "local",
    "lmstudio",
}

class IngressAdapter:
    """
    Intercepteur de requêtes MCP pour l'alignement de contexte.
    """

    @staticmethod
    def qualify_session(agent: str, method: str, params: Dict[str, Any], base_ring: int) -> int:
        """
        Calcule le ring de session dynamique.
        
        Args:
            agent: Identifiant de l'agent (ex: CLAUDE, GEMINI)
            method: Méthode JSON-RPC (ex: tools/call)
            params: Paramètres de l'appel
            base_ring: Ring d'origine de l'agent
            
        Returns:
            int: Ring de session effectif (0-4)
        """
        # 1. Si ce n'est pas un appel d'outil LLM, on garde le base_ring
        if method != "tools/call":
            return base_ring

        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        
        # 2. Détection de la destination d'inférence (pour ask, route_task, etc.)
        target_provider = str(args.get("provider", "auto")).lower()
        target_model = str(args.get("model", "")).lower()

        # Inférence directe via outils spécialisés
        is_cloud_tool = tool_name in ("ask_gemini", "ask_claude", "ask_openai", "ask_groq")
        is_local_tool = tool_name in ("ask_ollama", "ask_llamacpp", "ask_local")

        # Qualification du provider dans les arguments
        is_cloud_provider = any(p in target_provider or p in target_model for p in CLOUD_PROVIDERS)
        is_local_provider = any(p in target_provider or p in target_model for p in LOCAL_PROVIDERS)

        # Synthèse de la destination
        is_cloud = is_cloud_tool or (is_cloud_provider and not is_local_provider)
        is_local = is_local_tool or is_local_provider

        # 3. Application du Dogme de Confinement
        # Si la destination est Cloud (ou outil cloud direct), on s'effondre en Ring 4
        if is_cloud and not is_local:
            logger.info(f"[ingress] Confinement CLOUD détecté ({tool_name}/{target_provider}) -> Ring 4")
            return int(IntegrityRing.UNTRUSTED) # Ring 4

        # 4. Tâches sensibles (Nature de la tâche)
        # Si l'outil lui-même est un outil d'exécution déporté
        if tool_name in ("run", "ps_run", "execute", "orchestrate"):
            # L'exécution n'est autorisée que si le ring de base le permet
            # et qu'on n'est pas dans un flux cloud forcé.
            return base_ring

        return base_ring

    @staticmethod
    def filter_tools(tools: list, session_ring: int) -> list:
        """
        Purge le catalogue d'outils présenté au modèle selon le ring de session.
        
        Args:
            tools: Liste des définitions d'outils MCP
            session_ring: Ring calculé pour cette session
            
        Returns:
            list: Catalogue filtré
        """
        if session_ring <= int(IntegrityRing.TRUSTED): # Ring 0, 1, 2
            return tools

        # Ring 4 (UNTRUSTED / Confinement)
        filtered = []
        for t in tools:
            name = t.get("name", "")
            if name in RING_4_ALLOWLIST:
                filtered.append(t)
            else:
                # On remplace par un stub ou on supprime simplement
                pass
        
        logger.debug(f"[ingress] Outils filtrés pour Ring {session_ring}: {len(filtered)}/{len(tools)}")
        return filtered

_adapter: Optional[IngressAdapter] = None

def get_ingress_adapter() -> IngressAdapter:
    global _adapter
    if _adapter is None:
        _adapter = IngressAdapter()
    return _adapter
